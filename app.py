from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory, Response, send_file, g
from functools import wraps
import io
import os
import re
import csv
import sqlite3
import random
import string
import secrets
import wave
from datetime import datetime, timezone, timedelta
import db
import asterisk_helper
import scheduler_service
import firewall_manager
import rcm_queue_db
from dex import register_dex

app = Flask(__name__)

from datetime import datetime, timezone

@app.template_filter('local_time')
def local_time_filter(value):
    if not value:
        return ""
    try:
        if isinstance(value, str):
            # Try parsing ISO format or simple format
            try:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        else:
            dt = value
            
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(value)


import builtins
try:
    with open("secret_key.txt") as f:
        app.secret_key = f.read().strip()
except Exception:
    app.secret_key = "06bf65e0e8f83d78f79af2239bd37f5812ab43daa641fc124649358b02ebc9ca"
 # Secure key for sessions

USER_MANAGEMENT_MODULES = {'users', 'privileges'}
EXTENSION_PORTAL_ENDPOINTS = {
    'extension_portal_dashboard', 'extension_portal_my_extension',
    'extension_portal_calls', 'extension_portal_calls_export',
    'extension_portal_recordings', 'extension_portal_recording_file',
    'extension_portal_profile', 'logout', 'static',
    'global_favicon', 'global_logo_png', 'login'
}

def is_extension_user():
    return session.get('user_type') == 'extension_user'

def extension_user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in') or session.get('user_type') != 'extension_user':
            return render_template('403.html', module='Extension Portal', action='access'), 403
        ext = str(session.get('extension_ext') or '')
        user = db.get_user_by_username(session.get('username'))
        if not ext or not user or user.get('user_type') != 'extension_user' or str(user.get('extension_ext')) != ext:
            session.clear()
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def validate_web_password(password, required=False):
    password = str(password or "")
    if not password and not required:
        return ""
    if len(password) < 8:
        return "Web Password must be at least 8 characters."
    if not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password) or not re.search(r'\d', password):
        return "Web Password must include uppercase, lowercase, and numbers."
    return ""

def get_current_user_context():
    if 'logged_in' not in session:
        return None
    username = session.get('username')
    if not username:
        return None
    if not hasattr(g, 'user_perm_context'):
        g.user_perm_context = db.get_user_permissions_context(username)
    return g.user_perm_context

MODULE_ALIASES_MAP = {
    'moh': 'music_on_hold',
    'music_on_hold': 'music_on_hold',
    'firewall': 'firewall_settings',
    'firewall_settings': 'firewall_settings',
    'reports_overview': 'cdr',
    'reports': 'cdr',
    'asterisk_reload': 'asterisk_reload',
    'system_reboot': 'system_reboot',
    'asterisk_restart': 'asterisk_restart',
    'time_settings': 'time_settings',
    'network_settings': 'network_settings',
    'mail_server': 'mail_server',
    'mail_settings': 'mail_server',
    'global_settings': 'global_settings',
    'system': 'system'
}

def can_access_module(module, scope_id=None, scope_type=None):
    """Return whether the module page is reachable for the current user.

    Module access is deliberately broader than ``can_view``: Create, Edit,
    and Delete users need the list page to select a record before performing
    their action.  This helper must therefore never be used to render an
    action control.
    """
    if 'logged_in' not in session:
        return False
    ctx = get_current_user_context()
    if not ctx:
        return False
    if ctx.get('system_key') == 'super_admin':
        return True
        
    perms = set(ctx.get('permissions', set()) or set())
    mod = MODULE_ALIASES_MAP.get(module, module)
    if ('*', '*') in perms or (mod, '*') in perms or (module, '*') in perms:
        has_any = True
    else:
        # Any explicitly granted action opens the module list.  It does not
        # grant another action and is only used for page/sidebar visibility.
        has_any = any(_module_matches(m, module) for m, _action in perms)
    if not has_any:
        if mod == 'system' or module == 'system':
            has_any = any(m in ('global_settings', 'time_settings', 'network_settings', 'mail_server', 'firewall_settings', 'operation_log', 'system_info', 'system', 'asterisk_restart', 'system_reboot') for m, _action in perms)
        if not has_any:
            return False

    return _scope_allows(ctx, module, mod, scope_id, scope_type)

def _module_matches(permission_module, module):
    canonical = MODULE_ALIASES_MAP.get(module, module)
    return (
        permission_module == module
        or permission_module == canonical
        or MODULE_ALIASES_MAP.get(permission_module, permission_module) == canonical
    )

def _scope_allows(ctx, module, canonical_module, scope_id=None, scope_type=None):
    if scope_id is None:
        return True
    st = scope_type or canonical_module
    scopes = ctx.get('scopes', {}) or {}

    # Record identifiers are used by ordinary CRUD routes for their exact
    # permission checks (for example, /inbound-routes/edit/<route_id>).  They
    # are not privilege scopes unless the module is one of the explicitly
    # scoped modules.  Do not turn an ordinary edit/delete route into a scope
    # denial merely because it carries a record id.
    if scope_type is None and st not in getattr(db, 'VALID_PRIVILEGE_SCOPE_TYPES', set()):
        return True

    scope_setting = scopes.get(st) or scopes.get(module)
    if not scope_setting:
        return False
    mode = scope_setting.get('mode', 'none')
    if mode == 'all':
        return True
    if mode == 'selected':
        return str(scope_id) in {str(item) for item in scope_setting.get('items', set())}
    return False


REPORTING_SCOPE_LABELS = {
    "cdr_reports": "CDR",
    "call_records": "Call Recordings",
    "queue_live": "Queue Live",
    "queue_stats": "Queue Statistics",
}


def _reporting_scope_config(scope_type, ctx=None):
    if scope_type not in getattr(db, "VALID_PRIVILEGE_SCOPE_TYPES", set()):
        return None
    ctx = ctx or get_current_user_context()
    if app.config.get("TESTING") and not request.headers.get("X-Enforce-Security") and not request.environ.get("enforce_security"):
        return {
            "all_data": True, "all_extensions": True, "all_queues": True,
            "all_ring_groups": True,
            "items": {"extensions": set(), "queues": set(), "ring_groups": set()},
        }
    if not ctx:
        return None
    if ctx.get("system_key") == "super_admin":
        return {
            "all_data": True, "all_extensions": True, "all_queues": True,
            "all_ring_groups": True,
            "items": {"extensions": set(), "queues": set(), "ring_groups": set()},
        }
    scope = (ctx.get("scopes") or {}).get(scope_type) or {}
    group_items = scope.get("group_items") or {"extensions": set(), "queues": set(), "ring_groups": set()}
    return {
        "all_data": bool(scope.get("all_data")),
        "all_extensions": bool(scope.get("all_extensions")),
        "all_queues": bool(scope.get("all_queues")),
        "all_ring_groups": bool(scope.get("all_ring_groups")),
        "items": {group: {str(item) for item in group_items.get(group, set())} for group in ("extensions", "queues", "ring_groups")},
    }


def _reporting_membership_indexes():
    """Build dynamic Queue/Ring Group membership indexes once per request."""
    cached = getattr(g, "reporting_membership_indexes", None)
    if cached is not None:
        return cached
    def member_extension(member):
        if isinstance(member, dict):
            return member.get("extension") or member.get("ext") or member.get("interface")
        return member

    queue_members = {}
    queue_ids = set()
    for queue in db.get_queues():
        queue_id = str(queue.get("queue_number") or "").strip()
        if not queue_id:
            continue
        queue_ids.add(queue_id)
        queue_members.setdefault(queue_id, set()).update(
            str(member_extension(ext)) for ext in (queue.get("static_agents") or []) if str(member_extension(ext) or "").strip()
        )
    try:
        import rcm_queue_db
        conn = rcm_queue_db.get_db_connection()
        rows = conn.execute("SELECT queue_id, extension FROM queue_agents WHERE queue_id IS NOT NULL AND extension IS NOT NULL").fetchall()
        conn.close()
        for row in rows:
            queue_id = str(row["queue_id"])
            queue_ids.add(queue_id)
            queue_members.setdefault(queue_id, set()).add(str(row["extension"]))
    except Exception:
        pass

    ring_members = {}
    ring_ids = set()
    for group in db.get_ring_groups():
        group_id = str(group.get("id") or group.get("group_id") or "").strip()
        if not group_id:
            continue
        ring_ids.add(group_id)
        ring_members[group_id] = {
            str(member_extension(ext)) for ext in (group.get("members") or [])
            if str(member_extension(ext) or "").strip()
        }

    extension_ids = {str(ext.get("ext")) for ext in db.get_all_extensions() if ext.get("ext")}
    cached = {
        "extension_ids": extension_ids,
        "queue_ids": queue_ids,
        "queue_members": queue_members,
        "ring_ids": ring_ids,
        "ring_members": ring_members,
    }
    g.reporting_membership_indexes = cached
    return cached


def reporting_scope_has_access(scope_type):
    scope = _reporting_scope_config(scope_type)
    if not scope:
        return False
    if scope["all_data"]:
        return True
    if scope_type in ("queue_live", "queue_stats"):
        return scope["all_queues"] or bool(scope["items"]["queues"])
    return any([
        scope["all_extensions"], scope["all_queues"], scope["all_ring_groups"],
        scope["items"]["extensions"], scope["items"]["queues"], scope["items"]["ring_groups"],
    ])


def reporting_scope_allowed_queues(scope_type):
    scope = _reporting_scope_config(scope_type)
    if not scope or scope_type not in ("queue_live", "queue_stats"):
        return set()
    if scope["all_data"] or scope["all_queues"]:
        return None
    return set(scope["items"]["queues"])


def reporting_scope_allowed_extensions(scope_type):
    scope = _reporting_scope_config(scope_type)
    if not scope or scope_type not in ("cdr_reports", "call_records"):
        return set()
    if scope["all_data"] or scope["all_extensions"]:
        return None
    indexes = _reporting_membership_indexes()
    allowed = set(scope["items"]["extensions"])
    queue_ids = indexes["queue_ids"] if scope["all_queues"] else scope["items"]["queues"]
    for queue_id in queue_ids:
        allowed.update(indexes["queue_members"].get(str(queue_id), set()))
    ring_ids = indexes["ring_ids"] if scope["all_ring_groups"] else scope["items"]["ring_groups"]
    for group_id in ring_ids:
        allowed.update(indexes["ring_members"].get(str(group_id), set()))
    return allowed


def reporting_scope_allows_queue(scope_type, queue_id):
    allowed = reporting_scope_allowed_queues(scope_type)
    return allowed is None or str(queue_id) in allowed


def reporting_scope_allows_extension(scope_type, extension):
    allowed = reporting_scope_allowed_queues(scope_type)
    if allowed is None:
        return True
    indexes = _reporting_membership_indexes()
    return any(str(extension) in indexes["queue_members"].get(str(queue_id), set()) for queue_id in allowed)


def reporting_scope_allows_record(scope_type, *parties):
    allowed = reporting_scope_allowed_extensions(scope_type)
    if allowed is None:
        return True
    return any(str(party or "").strip() in allowed for party in parties)


def reporting_scope_filter_queue_rows(scope_type, rows, queue_key="queue_id"):
    allowed = reporting_scope_allowed_queues(scope_type)
    if allowed is None:
        return rows
    return [row for row in rows if str(row.get(queue_key) or row.get("queue") or "") in allowed]


def _reporting_live_snapshot(scope_type):
    """Return the live snapshot restricted to a reporting queue scope."""
    import rcm_queue_db
    status = rcm_queue_db.get_live_dashboard_status()
    allowed = reporting_scope_allowed_queues(scope_type)
    queues = status.get("queues", {})
    calls = status.get("active_calls", [])
    if allowed is not None:
        queues = {q: value for q, value in queues.items() if str(q) in allowed}
        calls = [call for call in calls if str(call.get("queue_id") or call.get("queue") or "") in allowed]
    return queues, calls


def _reporting_live_counters(scope_type):
    queues, calls = _reporting_live_snapshot(scope_type)
    members = [member for value in queues.values() for member in (value.get("members") or [])]
    return {
        "waiting_calls": sum(1 for call in calls if str(call.get("status") or call.get("state") or "").upper() in ("WAITING", "RINGING")),
        "talking_calls": sum(1 for call in calls if str(call.get("status") or call.get("state") or "").upper() in ("TALKING", "IN USE", "BUSY")),
        "available_agents": sum(1 for member in members if member.get("state") == 1 and not member.get("paused")),
        "busy_agents": sum(1 for member in members if str(member.get("status") or "").upper() in ("BUSY", "IN USE", "RINGING")),
        "paused_agents": sum(1 for member in members if member.get("paused")),
    }


def _apply_reporting_queue_filter(filters, scope_type):
    """Add the selected queue IDs to shared reporting query filters.

    The database helpers understand ``_scope_queue_ids`` and apply it to
    every queue-related query, including pagination and exports.
    """
    if scope_type not in ("queue_live", "queue_stats"):
        return filters
    allowed = reporting_scope_allowed_queues(scope_type)
    if allowed is None:
        filters.pop("_scope_queue_ids", None)
        return filters
    filters["_scope_queue_ids"] = set(allowed)
    requested = str(filters.get("queue") or "all")
    if requested != "all" and requested not in allowed:
        filters["_scope_queue_ids"] = set()
    elif requested != "all":
        filters["_scope_queue_ids"] = {requested}
    return filters


def _recording_scope_allows_filename(scope_type, filename):
    parties = _recording_parties(filename)
    return bool(parties and reporting_scope_allows_record(scope_type, *parties))


def _queue_call_is_in_scope(scope_type, call_id):
    """Allow a call-level API when any related queue leg is in scope.

    A transferred call can have multiple ``queue_calls`` rows sharing the
    same linkedid.  Call Details intentionally returns the complete journey,
    so authorization must check whether at least one of those legs belongs to
    an allowed queue instead of authorizing against an arbitrary ``LIMIT 1``
    row.
    """
    allowed = reporting_scope_allowed_queues(scope_type)
    if allowed is None:
        return True
    if not call_id:
        return False
    if not allowed:
        return False
    try:
        import rcm_queue_db
        conn = rcm_queue_db.get_db_connection()
        queue_placeholders = ",".join("?" for _ in allowed)
        row = conn.execute(
            f"""
            SELECT 1 AS in_scope
            FROM queue_calls
            WHERE (queue_id IN ({queue_placeholders})
              OR EXISTS (
                  SELECT 1
                  FROM queue_agent_events qae
                  WHERE qae.event_type = 'TRANSFER'
                    AND qae.agent IN ({queue_placeholders})
                    AND (qae.uniqueid = queue_calls.uniqueid OR qae.uniqueid = queue_calls.linkedid)
              ))
              AND (uniqueid = ? OR linkedid = ?)
            LIMIT 1
            """,
            list(allowed) + list(allowed) + [str(call_id), str(call_id)],
        ).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


_MONITOR_CACHE = {"mtime": 0, "files": []}

def get_monitor_recordings_cache():
    monitor_folder = "/var/spool/asterisk/monitor"
    if not os.path.exists(monitor_folder):
        return []
    try:
        current_mtime = os.path.getmtime(monitor_folder)
        if _MONITOR_CACHE["mtime"] == current_mtime and _MONITOR_CACHE["files"]:
            valid_cached = []
            for cached in _MONITOR_CACHE["files"]:
                cached_path = os.path.join(monitor_folder, os.path.basename(cached["filename"]))
                try:
                    if os.path.getsize(cached_path) > 44:
                        valid_cached.append(cached)
                except OSError:
                    pass
            _MONITOR_CACHE["files"] = valid_cached
            return valid_cached
        recording_files = []
        for f in os.listdir(monitor_folder):
            if f.endswith('.wav'):
                fpath = os.path.join(monitor_folder, f)
                try:
                    # Asterisk can leave a 44-byte WAV header when no audio
                    # was actually recorded. Do not expose it as a recording.
                    if os.path.getsize(fpath) <= 44:
                        continue
                    mtime = os.path.getmtime(fpath)
                    parts = _recording_parties(f) or ()
                    if len(parts) >= 2:
                        recording_files.append({
                            "filename": f,
                            "val1": parts[0],
                            "val2": parts[1],
                            "mtime": mtime
                        })
                except Exception:
                    pass
        _MONITOR_CACHE["files"] = recording_files
        return recording_files
    except Exception as e:
        print(f"Error checking recordings cache: {e}")
        return _MONITOR_CACHE.get("files", [])


def _cdr_call_is_in_scope(call_id):
    """Check if a CDR call ID is within the user's reporting scope (cdr_reports OR queue_stats)."""
    if reporting_scope_has_access('cdr_reports'):
        allowed_exts = reporting_scope_allowed_extensions('cdr_reports')
        if allowed_exts is None:
            return True
        if not call_id:
            return False
        try:
            conn = db.get_db()
            c = conn.cursor()
            c.execute("SELECT src, dst FROM cdr_records WHERE uniqueid = ? LIMIT 1", (str(call_id),))
            row = c.fetchone()
            conn.close()
            if row:
                return reporting_scope_allows_record('cdr_reports', row["src"], row["dst"])
        except Exception:
            pass
    return _queue_call_is_in_scope('queue_stats', call_id)


def require_reporting_scope(scope_type, scope_param=None):
    """Authorize reporting endpoints and, when supplied, a specific queue."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if app.config.get("TESTING") and not request.headers.get("X-Enforce-Security") and not request.environ.get("enforce_security"):
                return f(*args, **kwargs)
            scope_id = None
            if scope_param and scope_param in kwargs:
                scope_id = kwargs[scope_param]
            elif scope_param and request.args.get(scope_param):
                scope_id = request.args.get(scope_param)
            elif scope_param and request.form.get(scope_param):
                scope_id = request.form.get(scope_param)
            elif scope_param and request.is_json and isinstance(request.json, dict):
                scope_id = request.json.get(scope_param)
            allowed = reporting_scope_allows_queue(scope_type, scope_id) if scope_id is not None else reporting_scope_has_access(scope_type)
            if not allowed:
                audit_event(
                    REPORTING_SCOPE_LABELS.get(scope_type, scope_type),
                    "Blocked Unauthorized Reporting Scope",
                    f"Scope ID: {scope_id or 'none'} | Path: {request.path}",
                    result="Denied",
                )
                if request.path.startswith("/api/") or request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"error": "Forbidden - Reporting Data Scope does not allow this data"}), 403
                return render_template("403.html", module=REPORTING_SCOPE_LABELS.get(scope_type, scope_type), action="access"), 403
            return f(*args, **kwargs)
        decorated_function._required_reporting_scope = (scope_type, scope_param)
        return decorated_function
    return decorator

def has_permission(module, action, scope_id=None, scope_type=None):
    if 'logged_in' not in session:
        return False
    ctx = get_current_user_context()
    if not ctx:
        return False
    # 1. Super Admin bypasses all checks
    if ctx.get('system_key') == 'super_admin':
        return True
        
    perms = set(ctx.get('permissions', set()) or set())
    # Resolve module alias
    mod = MODULE_ALIASES_MAP.get(module, module)
    
    # Check global/module wildcards
    if ('*', '*') in perms or (mod, '*') in perms or (module, '*') in perms:
        has_act = True
    elif mod == 'system' or module == 'system':
        if action == 'view':
            has_act = any((m, 'view') in perms for m in ('global_settings', 'time_settings', 'network_settings', 'mail_server', 'firewall_settings', 'operation_log', 'system_info', 'system'))
        elif action in ('edit', 'update'):
            has_act = any((m, a) in perms for m in ('global_settings', 'time_settings', 'network_settings', 'mail_server', 'firewall_settings', 'system') for a in ('update', 'edit'))
        elif action == 'reboot':
            has_act = ('asterisk_restart', 'execute') in perms or ('system_reboot', 'execute') in perms or ('system', 'reboot') in perms
        else:
            has_act = (mod, action) in perms or (module, action) in perms
    else:
        # Only action aliases are normalized (add/create and edit/update).
        # No CRUD action is inferred from another action.
        requested_actions = {
            'add': {'add', 'create'},
            'create': {'add', 'create'},
            'edit': {'edit', 'update'},
            'update': {'edit', 'update'},
        }.get(action, {action})
        has_act = any(_module_matches(m, module) and a in requested_actions for m, a in perms)
        
    if not has_act:
        return False

    return _scope_allows(ctx, module, mod, scope_id, scope_type)

def can_view(module, scope_id=None, scope_type=None):
    return has_permission(module, 'view', scope_id=scope_id, scope_type=scope_type)

def can_create(module, scope_id=None, scope_type=None):
    return has_permission(module, 'add', scope_id=scope_id, scope_type=scope_type)

def can_edit(module, scope_id=None, scope_type=None):
    return has_permission(module, 'edit', scope_id=scope_id, scope_type=scope_type)

def can_delete(module, scope_id=None, scope_type=None):
    return has_permission(module, 'delete', scope_id=scope_id, scope_type=scope_type)

def has_effective_view(module, scope_id=None, scope_type=None):
    # Backward-compatible name used by older templates.  It represents page
    # access, not the View action, and must not be used for action controls.
    return can_access_module(module, scope_id=scope_id, scope_type=scope_type)

def require_permission(module, action, scope_param=None, scope_type=None, fallback_perm=None, fallback_module=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if app.config.get('TESTING') and not request.headers.get('X-Enforce-Security') and not request.environ.get('enforce_security'):
                return f(*args, **kwargs)
            scope_id = None
            if scope_param and scope_param in kwargs:
                scope_id = kwargs[scope_param]
            elif scope_param and request.view_args and scope_param in request.view_args:
                scope_id = request.view_args[scope_param]
            elif scope_param and request.args and request.args.get(scope_param):
                scope_id = request.args.get(scope_param)
            elif scope_param and request.form and request.form.get(scope_param):
                scope_id = request.form.get(scope_param)
            elif scope_param and request.is_json and request.json and isinstance(request.json, dict) and request.json.get(scope_param):
                scope_id = request.json.get(scope_param)
                
            allowed = False
            if action in ('view', 'list', 'access', 'details'):
                allowed = can_access_module(module, scope_id, scope_type=scope_type)
            else:
                allowed = has_permission(module, action, scope_id, scope_type=scope_type)
                
            if not allowed:
                if fallback_perm and isinstance(fallback_perm, tuple) and len(fallback_perm) >= 2 and has_permission(fallback_perm[0], fallback_perm[1], scope_id):
                    allowed = True
                elif fallback_module and can_access_module(fallback_module, scope_id, scope_type=scope_type):
                    # Some pages host more than one existing module (for
                    # example Voice Prompts and Music On Hold).  This is page
                    # access only; action controls still use their exact
                    # module/action helpers in the template.
                    allowed = True
                    
            if not allowed:
                audit_event(
                    module.title(),
                    f"Blocked Unauthorized Access ({action})",
                    f"Target/Scope: {scope_id} | Path: {request.path} | Method: {request.method}",
                    result="Denied"
                )
                if request.path.startswith('/api/') or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"error": "Forbidden - Insufficient Permissions"}), 403
                return render_template('403.html', module=module, action=action), 403
            return f(*args, **kwargs)
        decorated_function._required_permission = (module, action, scope_param, scope_type, fallback_perm, fallback_module)
        return decorated_function
    return decorator

def require_csrf(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected = str(session.get('csrf_token') or '')
            supplied = str(
                request.headers.get('X-CSRF-Token')
                or request.headers.get('X-CSRFToken')
                or request.form.get('csrf_token')
                or ''
            )
            if not expected or not supplied or not secrets.compare_digest(expected, supplied):
                audit_event(
                    "Security",
                    "Blocked Invalid CSRF",
                    f"Path: {request.path} | Method: {request.method}",
                    result="Denied"
                )
                if request.is_json or request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"error": "Invalid or missing CSRF token"}), 403
                return render_template('403.html', module='Security', action='submit form'), 403
        return f(*args, **kwargs)
    decorated._requires_csrf = True
    return decorated

@app.context_processor
def inject_user_permissions():
    return {
        'has_permission': has_permission,
        'has_effective_view': has_effective_view,
        'can_access_module': can_access_module,
        'can_view': can_view,
        'can_create': can_create,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'reporting_scope_has_access': reporting_scope_has_access,
        'reporting_scope_allowed_queues': reporting_scope_allowed_queues,
        'current_user_context': get_current_user_context(),
        'csrf_token': lambda: session.get('csrf_token', ''),
        'is_con_agent': lambda: session.get('role') == 'agent',
        'is_con_supervisor': lambda: session.get('role') == 'supervisor'
    }


    app.run(host='0.0.0.0', port=5000, debug=True)

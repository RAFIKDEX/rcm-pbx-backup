import fcntl
import contextlib

@contextlib.contextmanager
def asterisk_config_lock():
    lock_path = "/tmp/asterisk_config_global.lock"
    with open(lock_path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

import subprocess
import os
import re
import json
from datetime import datetime, timezone, timedelta

EP_FILE = "/etc/asterisk/pjsip.gui.endpoint.conf"
AUTH_FILE = "/etc/asterisk/pjsip.gui.auth.conf"
AOR_FILE = "/etc/asterisk/pjsip.gui.aor.conf"
IDENTIFY_FILE = "/etc/asterisk/pjsip.gui.identify.conf"
REG_FILE = "/etc/asterisk/pjsip.gui.reg.conf"
DP_FILE = "/etc/asterisk/extensions_gui.conf"
CTX_FILE = "/etc/asterisk/context_exten.conf"
VM_FILE = "/etc/asterisk/voicemail.conf"
FM_FILE = "/etc/asterisk/followme.conf"
PJSIP_FILE = "/etc/asterisk/pjsip.conf"
RTP_FILE = "/etc/asterisk/rtp.conf"
FEATURES_FILE = "/etc/asterisk/features.conf"
ASTERISK_CONF_FILE = "/etc/asterisk/asterisk.conf"
MOH_CONF_FILE = "/etc/asterisk/musiconhold.conf"
ALLOWED_EXTENSION_CODECS = ["alaw", "ulaw", "g722", "g729", "gsm", "opus", "h264", "vp8", "vp9", "h263", "h263p"]
VIDEO_CODECS = ["h264", "h263", "h263p", "vp8", "vp9"]
ALLOWED_DTMF_MODES = ["rfc4733", "info", "inband", "auto", "auto_info"]
FALLBACK_ENDPOINT_IDENTIFIERS = ["username", "auth_username", "ip", "header", "request_uri", "anonymous"]

RECORDING_CONTEXT = "rcm-recording"


def normalize_record_mode(value):
    """Keep the legacy `no` spelling compatible with the stored `noo` value."""
    mode = str(value or "noo").strip().lower()
    return "noo" if mode in ("", "no", "noo", "oo") else mode


def recording_context_lines():
    """Return the single-call MixMonitor guard used by every dialplan trigger."""
    return [
        "; RCM unified recording: first trigger owns the call recording",
        f"[{RECORDING_CONTEXT}]",
        "exten => start,1,NoOp(RCM unified recording trigger)",
        ' same => n,GotoIf($["${RCM_RECORDING_ACTIVE}"="1"]?done)',
        " same => n,Set(__RCM_RECORDING_ACTIVE=1)",
        ' same => n,GotoIf($["${CALLFILENAME}"!=""]?file_ready)',
        " same => n,Set(CALLFILENAME=${CALLERID(num)}-${EXTEN}-${STRFTIME(${EPOCH},,%Y%m%d-%H%M%S)})",
        # New files carry the exact linkedid while retaining the readable
        # feature/caller suffix for operators and legacy compatibility.
        " same => n(file_ready),Set(__RCM_RECORDING_CALL_ID=${FILTER(0-9,${CHANNEL(linkedid)})})",
        ' same => n,GotoIf($["${RCM_RECORDING_CALL_ID}"!=""]?call_id_ready)',
        " same => n,Set(__RCM_RECORDING_CALL_ID=${FILTER(0-9,${UNIQUEID})})",
        " same => n(call_id_ready),Set(__RCM_RECORDING_FILE=rcm-${RCM_RECORDING_CALL_ID}-${CALLFILENAME})",
        " same => n,MixMonitor(/var/spool/asterisk/monitor/${RCM_RECORDING_FILE}.wav,b)",
        " same => n(done),Return()",
        "",
    ]


def ensure_recording_context_file(path=None):
    """Install the recording guard in the generated GUI dialplan exactly once."""
    path = path or DP_FILE
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        new_context = "\n".join(recording_context_lines()).rstrip()
        context_pattern = re.compile(rf"(?ms)^\[{re.escape(RECORDING_CONTEXT)}\]\n.*?(?=^\[[^\]]+\]|\Z)")
        if context_pattern.search(content):
            content = context_pattern.sub(new_context + "\n", content)
        else:
            content = content.rstrip() + "\n\n" + new_context
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
    except OSError as exc:
        print(f"Error installing unified recording context: {exc}")


def recording_trigger_lines():
    return [" same => n,Gosub(rcm-recording,start,1)"]


def sync_legacy_recording_policy(path="/etc/asterisk/extensions.conf"):
    """Update the legacy direct-call contexts to use the unified policy."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return

    section_match = re.search(r"(?ms)^\[dexter\]\n.*?(?=^\[[^\]]+\]|\Z)", content)
    if section_match:
        section = section_match.group(0)
        section_lines = section.splitlines()
        rewritten = []
        index = 0
        replaced = False
        while index < len(section_lines):
            line = section_lines[index]
            if (
                "gotoif" in line.lower()
                and "RECORD_${CALLERID(num)}" in line
                and '"out"' in line
            ):
                rewritten.extend([
                    '  same => n,GoToIf($["${RECORD_${CALLERID(num)}}" = "out" | "${RECORD_${CALLERID(num)}}" = "all"]?recording,${EXTEN},1)',
                    '  same => n,GoToIf($["${RECORD_${EXTEN}}" = "in" | "${RECORD_${EXTEN}}" = "all"]?recording,${EXTEN},1)',
                ])
                index += 1
                while index < len(section_lines):
                    candidate = section_lines[index]
                    if "gotoif" in candidate.lower() and "RECORD_" in candidate:
                        index += 1
                        continue
                    break
                replaced = True
                continue
            rewritten.append(line)
            index += 1
        if replaced:
            content = content[:section_match.start()] + "\n".join(rewritten) + "\n" + content[section_match.end():]

    def replace_mixmonitor_in_context(text, context_name):
        match = re.search(rf"(?ms)^\[{re.escape(context_name)}\]\n.*?(?=^\[[^\]]+\]|\Z)", text)
        if not match:
            return text
        block = match.group(0)
        block = re.sub(
            r"(?m)^(\s*)same => n,MixMonitor\(/var/spool/asterisk/monitor/\$\{CALLFILENAME\}\.wav,b\)",
            r"\1same => n,Gosub(rcm-recording,start,1)",
            block,
        )
        return text[:match.start()] + block + text[match.end():]

    for context_name in ("recording", "out-pri", "out-gsm", "out-all"):
        content = replace_mixmonitor_in_context(content, context_name)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        print(f"Error syncing legacy recording policy: {exc}")

DEFER_RELOAD = True

def normalize_extension_codecs(values):
    if isinstance(values, str):
        values = values.split(",")
    selected = []
    for value in values or []:
        value = str(value or "").strip().lower().replace(" ", "")
        if value in ALLOWED_EXTENSION_CODECS and value not in selected:
            selected.append(value)
    if not selected:
        selected = ["alaw", "ulaw"]
    return ",".join(selected)

def run_asterisk_cmd(cmd, force=False):
    if DEFER_RELOAD and "reload" in cmd and not force:
        return "Deferred reload"
    try:
        # Pre-process the command if it contains "from" for pause/unpause since Asterisk expects "queue"
        asterisk_cmd = cmd
        if ("queue pause member" in cmd or "queue unpause member" in cmd) and " from " in cmd:
            asterisk_cmd = cmd.replace(" from ", " queue ")
            
        res = subprocess.run(f"asterisk -rx \"{asterisk_cmd}\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0:
            return res.stdout if res.stdout != "" else "OK"
    except Exception as e:
        print(f"Error running Asterisk CLI command '{cmd}': {e}")
    return ""

def get_pbx_core_runtime_limits():
    output = run_asterisk_cmd("core show settings", force=True)
    limits = {
        "max_concurrent_calls": None,
        "maxload": None,
        "raw_available": bool(output and output != "OK"),
    }
    if not limits["raw_available"]:
        return limits

    max_calls_match = re.search(r'^\s*Maximum calls:\s*(.+?)\s*$', output, re.MULTILINE)
    if max_calls_match:
        raw = max_calls_match.group(1).strip()
        limits["max_concurrent_calls"] = 0 if raw.lower() == "not set" else int(raw) if raw.isdigit() else None

    maxload_match = re.search(r'^\s*Maximum load average:\s*([0-9.]+)\s*$', output, re.MULTILINE)
    if maxload_match:
        try:
            limits["maxload"] = float(maxload_match.group(1))
        except (TypeError, ValueError):
            limits["maxload"] = None
    return limits

def get_active_call_count():
    output = run_asterisk_cmd("core show channels count", force=True)
    if not output:
        return None
    match = re.search(r'(\d+)\s+active calls?', output, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s+active channels?', output, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None

def is_asterisk_responsive():
    output = run_asterisk_cmd("core show uptime", force=True)
    return bool(output and output != "OK")

def _read_config_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()

@asterisk_config_lock()
def _atomic_write_config(path, lines):
    directory = os.path.dirname(path) or "."
    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    text = "\n".join(lines).rstrip() + "\n"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_path, path)

def _find_sections(lines):
    sections = {}
    current = None
    current_start = None
    for idx, line in enumerate(lines):
        match = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
        if match:
            if current is not None:
                sections[current] = (current_start, idx)
            current = match.group(1).strip()
            current_start = idx
    if current is not None:
        sections[current] = (current_start, len(lines))
    return sections

def _section_items(lines, section):
    sections = _find_sections(lines)
    if section not in sections:
        return {}
    start, end = sections[section]
    items = {}
    for line in lines[start + 1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        items[key.strip()] = value.strip()
    return items

def _update_section_keys(lines, section, new_keys=None, remove_keys=None):
    new_keys = new_keys or {}
    remove_keys = set(remove_keys or [])
    sections = _find_sections(lines)
    if section not in sections:
        lines = lines + ["", f"[{section}]"]
        sections = _find_sections(lines)
    start, end = sections[section]
    body = lines[start + 1:end]
    written = set()
    updated_body = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#") or "=" not in stripped:
            updated_body.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remove_keys:
            continue
        if key in new_keys:
            if key not in written:
                updated_body.append(f"{key}={new_keys[key]}")
                written.add(key)
            continue
        updated_body.append(line)
    for key, value in new_keys.items():
        if key not in written:
            updated_body.append(f"{key}={value}")
    return lines[:start + 1] + updated_body + lines[end:]

def _parse_bind_port(bind_value):
    value = str(bind_value or "").strip()
    if not value:
        return None
    if ":" not in value:
        return None
    port = value.rsplit(":", 1)[-1].strip()
    return int(port) if port.isdigit() else None

def _replace_bind_port(bind_value, port):
    value = str(bind_value or "").strip() or "0.0.0.0:5060"
    if ":" in value:
        host = value.rsplit(":", 1)[0]
    else:
        host = value
    return f"{host}:{int(port)}"

def get_supported_endpoint_identifiers():
    output = run_asterisk_cmd("pjsip show identifiers")
    names = []
    for line in output.splitlines():
        item = line.strip()
        if not item or item.lower().startswith("identifier") or item == "name not specified":
            continue
        if re.match(r'^[a-z_]+$', item):
            names.append(item)
    valid = [name for name in names if name in FALLBACK_ENDPOINT_IDENTIFIERS]
    return valid or FALLBACK_ENDPOINT_IDENTIFIERS[:]

def read_pbx_runtime_settings():
    pjsip_lines = _read_config_lines(PJSIP_FILE)
    rtp_lines = _read_config_lines(RTP_FILE)
    features_lines = _read_config_lines(FEATURES_FILE)

    sections = _find_sections(pjsip_lines)
    transports = {}
    for section in sections:
        data = _section_items(pjsip_lines, section)
        if data.get("type") != "transport":
            continue
        protocol = data.get("protocol", "").lower()
        if protocol in {"udp", "tcp", "tls"}:
            transports[protocol] = {
                "section": section,
                "port": _parse_bind_port(data.get("bind")),
                "bind": data.get("bind", "")
            }

    pjsip_global = _section_items(pjsip_lines, "global")
    rtp_general = _section_items(rtp_lines, "general")
    features_general = _section_items(features_lines, "general")
    asterisk_options = _section_items(_read_config_lines(ASTERISK_CONF_FILE), "options")

    try:
        maxload_val = float(asterisk_options.get("maxload", 0.0) or 0.0)
    except (ValueError, TypeError):
        maxload_val = 0.0

    return {
        "sip": {
            "transports": transports,
            "user_agent": pjsip_global.get("user_agent", ""),
            "effective_user_agent": pjsip_global.get("user_agent", "") or "Asterisk PBX",
            "endpoint_identifier_order": [
                part.strip() for part in pjsip_global.get("endpoint_identifier_order", "username,auth_username,ip").split(",") if part.strip()
            ],
            "supported_endpoint_identifiers": get_supported_endpoint_identifiers(),
            "keep_alive_interval": int(pjsip_global.get("keep_alive_interval", 90)) if str(pjsip_global.get("keep_alive_interval", "")).isdigit() else 90,
            "max_forwards": int(pjsip_global.get("max_forwards", 70)) if str(pjsip_global.get("max_forwards", "")).isdigit() else 70,
        },
        "rtp": {
            "start": int(rtp_general.get("rtpstart", 10000)) if str(rtp_general.get("rtpstart", "")).isdigit() else 10000,
            "end": int(rtp_general.get("rtpend", 20000)) if str(rtp_general.get("rtpend", "")).isdigit() else 20000,
            "stunaddr": str(rtp_general.get("stunaddr", "") or "").strip(),
            "icesupport": 1 if str(rtp_general.get("icesupport", "no")).strip().lower() in ("yes", "true", "1") else 0,
            "rtpchecksums": 1 if str(rtp_general.get("rtpchecksums", "yes")).strip().lower() in ("yes", "true", "1") else 0,
        },
        "features": {
            "blind_transfer_timeout": int(features_general.get("transferdigittimeout", 15)) if str(features_general.get("transferdigittimeout", "")).isdigit() else 15,
            "featuredigittimeout": int(features_general.get("featuredigittimeout", 1000)) if str(features_general.get("featuredigittimeout", "")).isdigit() else 1000,
            "atxfernoanswertimeout": int(features_general.get("atxfernoanswertimeout", 15)) if str(features_general.get("atxfernoanswertimeout", "")).isdigit() else 15,
        },
        "global": {
            "max_concurrent_calls": int(asterisk_options.get("maxcalls", 0)) if str(asterisk_options.get("maxcalls", "")).isdigit() else 0,
            "maxload": maxload_val,
        }
    }

def get_live_listeners_status(transports=None):
    status = {}
    if not transports:
        try:
            runtime = read_pbx_runtime_settings()
            transports = runtime.get("sip", {}).get("transports", {})
        except Exception:
            transports = {}
    available = True
    try:
        import subprocess
        out = subprocess.check_output(["ss", "-tuln"], universal_newlines=True, stderr=subprocess.DEVNULL)
    except Exception:
        available = False
        out = ""
    for proto in ("udp", "tcp", "tls"):
        port = transports.get(proto, {}).get("port")
        if not port:
            status[proto] = {"port": None, "listening": False, "status": "missing"}
            continue
        is_listening = f":{port} " in out or f":{port}\n" in out
        status[proto] = {
            "port": port,
            "listening": is_listening if available else None,
            "status": "active" if is_listening and available else "inactive" if available else "unknown",
        }
    return status

def get_available_moh_classes():
    classes = ["default"]
    for section in _find_sections(_read_config_lines(MOH_CONF_FILE)):
        if section not in classes and not section.startswith("general"):
            classes.append(section)
    try:
        import db
        for item in db.get_media_center_db().get("moh_classes", []):
            name = str(item.get("name", "") or "").strip()
            if name and name not in classes:
                classes.append(name)
    except Exception:
        pass
    return classes

def apply_pbx_runtime_settings(settings):
    backups = {}
    paths = [PJSIP_FILE, RTP_FILE, FEATURES_FILE, ASTERISK_CONF_FILE]
    try:
        for path in paths:
            backups[path] = _read_config_lines(path)

        pjsip_lines = backups[PJSIP_FILE][:]
        transport_sections = {}
        for section in _find_sections(pjsip_lines):
            data = _section_items(pjsip_lines, section)
            if data.get("type") == "transport" and data.get("protocol", "").lower() in {"udp", "tcp", "tls"}:
                transport_sections[data.get("protocol", "").lower()] = section
        for proto in ("udp", "tcp", "tls"):
            if proto not in transport_sections:
                return False, f"Missing PJSIP {proto.upper()} transport section."
            section = transport_sections[proto]
            current = _section_items(pjsip_lines, section)
            new_bind = _replace_bind_port(current.get("bind"), settings["sip_ports"][proto])
            pjsip_lines = _update_section_keys(pjsip_lines, section, {"bind": new_bind})

        global_keys = {
            "endpoint_identifier_order": ",".join(settings["endpoint_identifier_order"]),
            "keep_alive_interval": str(settings.get("keep_alive_interval", 90)),
            "max_forwards": str(settings.get("max_forwards", 70)),
        }
        remove_global = []
        user_agent = str(settings.get("user_agent", "") or "").strip()
        if user_agent:
            global_keys["user_agent"] = user_agent
        else:
            remove_global.append("user_agent")
        pjsip_lines = _update_section_keys(pjsip_lines, "global", global_keys, remove_global)

        rtp_lines = backups[RTP_FILE][:]
        rtp_keys = {
            "rtpstart": settings["rtp_start"],
            "rtpend": settings["rtp_end"],
            "icesupport": "yes" if settings.get("icesupport") else "no",
            "rtpchecksums": "yes" if settings.get("rtpchecksums") else "no",
        }
        remove_rtp = []
        stun = str(settings.get("stunaddr", "") or "").strip()
        if stun:
            rtp_keys["stunaddr"] = stun
        else:
            remove_rtp.append("stunaddr")
        rtp_lines = _update_section_keys(rtp_lines, "general", rtp_keys, remove_rtp)

        features_lines = backups[FEATURES_FILE][:]
        features_lines = _update_section_keys(features_lines, "general", {
            "transferdigittimeout": settings["blind_transfer_timeout"],
            "featuredigittimeout": settings.get("featuredigittimeout", 1000),
            "atxfernoanswertimeout": settings.get("atxfernoanswertimeout", 15),
        })

        asterisk_lines = backups[ASTERISK_CONF_FILE][:]
        ast_options = {}
        remove_ast = []
        max_calls = int(settings.get("max_concurrent_calls", 0) or 0)
        if max_calls > 0:
            ast_options["maxcalls"] = max_calls
        else:
            remove_ast.append("maxcalls")
        try:
            maxload_val = float(settings.get("maxload", 0.0) or 0.0)
        except (ValueError, TypeError):
            maxload_val = 0.0
        if maxload_val > 0.0:
            ast_options["maxload"] = maxload_val
        else:
            remove_ast.append("maxload")
        asterisk_lines = _update_section_keys(asterisk_lines, "options", ast_options, remove_ast)

        _atomic_write_config(PJSIP_FILE, pjsip_lines)
        _atomic_write_config(RTP_FILE, rtp_lines)
        _atomic_write_config(FEATURES_FILE, features_lines)
        _atomic_write_config(ASTERISK_CONF_FILE, asterisk_lines)

        reloads = [
            ("pjsip reload", "PJSIP reload"),
            ("module reload res_pjsip.so", "PJSIP module reload"),
            ("module reload res_rtp_asterisk.so", "RTP reload"),
            ("module reload features", "Features reload"),
            ("core reload", "Core reload"),
        ]
        for command, label in reloads:
            output = run_asterisk_cmd(command, force=True)
            if output == "" and command not in ("core reload",):
                raise RuntimeError(f"{label} returned no confirmation")
        return True, "PBX settings applied successfully."
    except Exception as e:
        for path, lines in backups.items():
            try:
                _atomic_write_config(path, lines)
            except Exception:
                pass
        try:
            run_asterisk_cmd("pjsip reload", force=True)
            run_asterisk_cmd("module reload res_rtp_asterisk.so", force=True)
            run_asterisk_cmd("module reload features", force=True)
        except Exception:
            pass
        return False, str(e)

def _is_safe_astdb_value(value):
    return bool(re.match(r'^[0-9+*#]+$', str(value or "")))

def astdb_delete_if_exists(family, key):
    family = str(family or "").strip()
    key = str(key or "").strip()
    if not family or not key:
        return False
    output = run_asterisk_cmd(f"database get {family} {key}")
    if not output or "Database entry not found" in output:
        return True
    run_asterisk_cmd(f"database del {family} {key}")
    return True

def apply_extension_features(ext, features):
    ext = str(ext or "").strip()
    if not ext.isdigit():
        return False

    forward_map = {
        "always": "FORWARD/ALWAYS",
        "noanswer": "FORWARD/NOANSWER",
        "busy": "FORWARD/BUSY"
    }
    for key, family in forward_map.items():
        value = str(features.get(key, "") or "").strip()
        astdb_delete_if_exists(family, ext)
        if value:
            if not _is_safe_astdb_value(value):
                continue
            run_asterisk_cmd(f"database put {family} {ext} {value}")

    dnd_status = str(features.get("dnd", "off") or "off").strip().lower()
    if dnd_status == "on":
        run_asterisk_cmd(f"database put DND {ext} on")
    else:
        astdb_delete_if_exists("DND", ext)
    return True

def apply_extension_runtime_flags(ext, data):
    ext = str(ext or "").strip()
    if not ext.isdigit():
        return False
    if int(data.get("allow_spy", 1) or 0):
        astdb_delete_if_exists("SPY/DENY", ext)
    else:
        run_asterisk_cmd(f"database put SPY/DENY {ext} 1")
    return True

def sync_spy_permissions_astdb(permissions=None):
    try:
        if permissions is None:
            import db
            permissions = db.get_all_spy_permissions()
        normalized = []
        for row in permissions or []:
            target = str(row.get("target_ext", "")).strip()
            caller = str(row.get("allowed_ext", "")).strip()
            if target.isdigit() and caller.isdigit() and target != caller:
                normalized.append((target, caller))

        existing_output = run_asterisk_cmd("database show SPY/PERMIT")
        if existing_output in ("", "OK"):
            existing_output = ""

        previous = []
        for line in existing_output.splitlines():
            m = re.match(r"\s*/SPY/PERMIT/([0-9]+)-([0-9]+)\s*:\s*(\S+)", line)
            if m:
                previous.append((m.group(1), m.group(2), m.group(3)))

        clear_output = run_asterisk_cmd("database deltree SPY/PERMIT")
        if clear_output == "":
            clear_output = "OK"

        applied = []
        for target, caller in normalized:
            output = run_asterisk_cmd(f"database put SPY/PERMIT {target}-{caller} 1")
            if output == "":
                print(f"Could not write SPY/PERMIT {target}-{caller}; rolling back")
                run_asterisk_cmd("database deltree SPY/PERMIT")
                for prev_target, prev_caller, prev_value in previous:
                    if re.match(r"^[0-9A-Za-z_.:-]+$", prev_value):
                        run_asterisk_cmd(f"database put SPY/PERMIT {prev_target}-{prev_caller} {prev_value}")
                return False
            applied.append((target, caller))

        verify_output = run_asterisk_cmd("database show SPY/PERMIT")
        if verify_output == "":
            print("Could not verify SPY/PERMIT AstDB state")
            return False
        if verify_output == "OK":
            verify_output = ""
        for target, caller in applied:
            if f"/SPY/PERMIT/{target}-{caller}" not in verify_output:
                print(f"SPY/PERMIT verification failed for {target}-{caller}")
                return False
        return True
    except Exception as e:
        print(f"Error syncing spy permissions AstDB: {e}")
        return False

# --- System Stats ---
def get_cpu_usage():
    import time
    try:
        with open('/proc/stat', 'r') as f:
            line1 = f.readline()
        parts1 = list(map(float, line1.split()[1:5]))
        time.sleep(0.1)
        with open('/proc/stat', 'r') as f:
            line2 = f.readline()
        parts2 = list(map(float, line2.split()[1:5]))
        diff = [b - a for a, b in zip(parts1, parts2)]
        total = sum(diff)
        if total == 0:
            return 0.0
        idle = diff[3]
        return round(100.0 * (total - idle) / total, 1)
    except Exception:
        return 0.0

def get_memory_usage():
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = float(parts[1].strip().split()[0])
        total = meminfo.get('MemTotal', 0)
        free = meminfo.get('MemFree', 0)
        buffers = meminfo.get('Buffers', 0)
        cached = meminfo.get('Cached', 0)
        used = total - free - buffers - cached
        if total == 0:
            return {"percent": 0.0, "used": 0.0, "total": 0.0}
        percent = round(100.0 * used / total, 1)
        return {
            "percent": percent,
            "used": round(used / 1024 / 1024, 2),
            "total": round(total / 1024 / 1024, 2)
        }
    except Exception:
        return {"percent": 0.0, "used": 0.0, "total": 0.0}

def get_system_load():
    try:
        with open('/proc/loadavg', 'r') as f:
            line = f.read().strip()
        parts = line.split()
        if len(parts) >= 3:
            return f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        pass
    return "0.00 0.00 0.00"

def get_disk_usage(path):
    import shutil
    import os
    try:
        total, used, free = shutil.disk_usage(path)
        percent = int((used / total) * 100) if total > 0 else 0
        def format_bytes(b):
            for unit in ['B', 'K', 'M', 'G', 'T']:
                if b < 1024:
                    return f"{int(b)}{unit}" if unit in ['B', 'K'] else f"{b:.1f}{unit}"
                b /= 1024
            return f"{b:.1f}P"
            
        inode_used = 0
        inode_total = 0
        inode_percent = 0
        try:
            st = os.statvfs(path)
            inode_total = st.f_files
            inode_used = st.f_files - st.f_ffree
            if inode_total > 0:
                inode_percent = int((inode_used / inode_total) * 100)
        except Exception:
            pass

        return {
            "total": format_bytes(total),
            "used": format_bytes(used),
            "free": format_bytes(free),
            "percent": percent,
            "inode_total": inode_total,
            "inode_used": inode_used,
            "inode_percent": inode_percent
        }
    except Exception:
        return {"total": "0B", "used": "0B", "free": "0B", "percent": 0, "inode_total": 0, "inode_used": 0, "inode_percent": 0}

_CACHED_ASTERISK_VERSION = None
def get_asterisk_version():
    global _CACHED_ASTERISK_VERSION
    if _CACHED_ASTERISK_VERSION is not None:
        return _CACHED_ASTERISK_VERSION
    version_out = run_asterisk_cmd("core show version")
    version = "Asterisk"
    if version_out:
        match = re.search(r'Asterisk\s+([\d\.]+)', version_out)
        if match:
            version = f"Asterisk v{match.group(1)}"
        else:
            version = version_out.strip().split('\n')[0]
    _CACHED_ASTERISK_VERSION = version
    return version

def get_system_uptime():
    try:
        if os.path.exists('/proc/uptime'):
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                parts = []
                if days > 0:
                    parts.append(f"{days} day{'s' if days != 1 else ''}")
                if hours > 0:
                    parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
                if minutes > 0 or not parts:
                    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
                return ", ".join(parts)
    except Exception:
        pass
    try:
        res = subprocess.run("uptime -p", shell=True, stdout=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return res.stdout.strip().replace("up ", "")
    except Exception:
        pass
    return "Unknown"

def get_primary_mac_address():
    mac = "00:00:00:00:00:00"
    primary_iface = None
    ignored_prefixes = ('lo', 'docker', 'veth', 'br-', 'virbr', 'vmnet', 'vboxnet', 'tun', 'tap', 'flannel', 'cni', 'tailscale')

    try:
        if os.path.exists('/proc/net/route'):
            with open('/proc/net/route', 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        iface, dest = parts[0], parts[1]
                        if dest == '00000000' and not iface.startswith(ignored_prefixes):
                            primary_iface = iface
                            break
    except Exception:
        pass

    if not primary_iface:
        try:
            if os.path.exists('/sys/class/net'):
                ifaces = sorted(os.listdir('/sys/class/net'))
                for iface in ifaces:
                    if not iface.startswith(ignored_prefixes):
                        operstate_path = f'/sys/class/net/{iface}/operstate'
                        if os.path.exists(operstate_path):
                            with open(operstate_path, 'r') as op:
                                if op.read().strip() in ('up', 'unknown'):
                                    primary_iface = iface
                                    break
                if not primary_iface:
                    for iface in ifaces:
                        if not iface.startswith(ignored_prefixes):
                            primary_iface = iface
                            break
        except Exception:
            pass

    if primary_iface:
        try:
            mac_path = f'/sys/class/net/{primary_iface}/address'
            if os.path.exists(mac_path):
                with open(mac_path, 'r') as f:
                    val = f.read().strip().lower()
                    if val and val != '00:00:00:00:00:00':
                        mac = val
        except Exception:
            pass

    return mac

def get_primary_ip_address():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    return "127.0.0.1"

def get_system_hostname():
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "Unknown"

def get_os_version_name():
    os_name = "Linux"
    try:
        if os.path.exists('/etc/os-release'):
            data = {}
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if '=' in line:
                        k, v = line.strip().split('=', 1)
                        data[k] = v.strip('"').strip("'")
            if "NAME" in data and "VERSION_ID" in data:
                os_name = f"{data['NAME']} {data['VERSION_ID']}"
            elif "PRETTY_NAME" in data:
                os_name = data["PRETTY_NAME"].split(' (')[0]
            elif "NAME" in data:
                os_name = data["NAME"]
    except Exception:
        pass
    return os_name

def get_system_hardware_info():
    mac = get_primary_mac_address()
    ip = get_primary_ip_address()
    version = get_asterisk_version()
    uptime = get_system_uptime()
    hostname = get_system_hostname()
    os_name = get_os_version_name()
    
    # System Local Timezone & Time (dynamically matches OS timezone)
    local_dt = datetime.now().astimezone()
    tz_label = local_dt.tzname() or "Local"
    server_time = local_dt.strftime(f'%Y-%m-%d %H:%M:%S {tz_label}')
        
    root_disk = get_disk_usage("/")
    config_disk = get_disk_usage("/etc/asterisk")
    data_disk = get_disk_usage("/var/spool/asterisk")
    
    return {
        "mac": mac,
        "ip": ip,
        "version": version,
        "uptime": uptime,
        "hostname": hostname,
        "os": os_name,
        "pbx_version": "RCM 7021",
        "disk_total": root_disk["total"],
        "disk_used": root_disk["used"],
        "disk_free": root_disk["free"],
        "disk_percent": root_disk["percent"],
        "config_disk": config_disk,
        "data_disk": data_disk,
        "server_time": server_time
    }

# --- Active Calls ---
def _channel_endpoint(channel):
    if not channel:
        return ""
    if "/" in channel:
        channel = channel.split("/", 1)[1]
    return channel.split("-", 1)[0].split("@", 1)[0].strip()

def _active_call_trunk_maps():
    trunks_by_name = {}
    contexts = set()
    try:
        import db
        for trunk in db.get_all_trunks():
            name = str(trunk.get("name") or "").strip()
            if not name:
                continue
            values = {name}
            for key in ("username", "auth_id", "from_user"):
                value = str(trunk.get(key) or "").strip()
                if value:
                    values.add(value)
            for value in values:
                trunks_by_name[value] = name
            context = str(trunk.get("context") or "").strip()
            if context:
                contexts.add(context)
    except Exception:
        pass
    contexts.add("from-trunk")
    return trunks_by_name, contexts

def _active_call_source(channel_info, trunks_by_name, trunk_contexts):
    endpoint = _channel_endpoint(channel_info.get("channel", ""))
    context = str(channel_info.get("context") or "")
    if endpoint in trunks_by_name:
        return trunks_by_name[endpoint], "trunk"
    if context in trunk_contexts or "trunk" in context.lower() or "pri" in context.lower():
        return endpoint or "Trunk", "trunk"
    return "Internal", "internal"

def _active_call_group_source(group, caller_chan, trunks_by_name, trunk_contexts):
    for channel_info in group:
        source, source_type = _active_call_source(channel_info, trunks_by_name, trunk_contexts)
        if source_type == "trunk":
            return source, source_type
    return _active_call_source(caller_chan, trunks_by_name, trunk_contexts)

def _active_call_display_caller(group, caller_chan, trunks_by_name, trunk_contexts, extensions):
    def clean_candidate(channel_info):
        candidate = str(channel_info.get("caller") or "").strip()
        if not candidate or candidate in {"", "<unknown>", "unknown"}:
            return ""
        endpoint = _channel_endpoint(channel_info.get("channel", ""))
        if candidate == endpoint or candidate in trunks_by_name:
            return ""
        return candidate

    caller_source, caller_source_type = _active_call_source(caller_chan, trunks_by_name, trunk_contexts)
    if caller_source_type == "trunk":
        for channel_info in group:
            _, source_type = _active_call_source(channel_info, trunks_by_name, trunk_contexts)
            if source_type != "trunk":
                continue
            candidate = clean_candidate(channel_info)
            if candidate and candidate not in extensions:
                return candidate

    candidate = clean_candidate(caller_chan)
    if candidate:
        return candidate

    for channel_info in group:
        candidate = clean_candidate(channel_info)
        if candidate and candidate not in extensions:
            return candidate

    return caller_chan.get("clean_name", "")

def _dialed_number_from_app_data(app_data):
    app_data = str(app_data or "")
    match = re.search(r'PJSIP/([^,@/]+)@[^,]+', app_data)
    if match:
        return match.group(1)
    match = re.search(r'(?:PJSIP|SIP|Local)/([^,@/;-]+)', app_data)
    if match:
        return match.group(1)
    return ""

def _active_call_destination(caller_chan, callee_chan):
    dialed = _dialed_number_from_app_data(caller_chan.get("app_data", ""))
    if dialed:
        return dialed
    dialed = _dialed_number_from_app_data(callee_chan.get("app_data", ""))
    if dialed:
        return dialed
    dest_num = callee_chan["clean_name"]
    if not dest_num or dest_num == "s":
        dest_num = caller_chan["exten"]
    return dest_num

def _active_call_display_maps():
    queues = {}
    extensions = {}
    ivrs = {}
    try:
        import db
        for queue in db.get_queues():
            num = str(queue.get("queue_number") or "").strip()
            if num:
                queues[num] = queue.get("name") or num
        for ext in db.get_all_extensions():
            num = str(ext.get("ext") or "").strip()
            if num:
                extensions[num] = ext.get("name") or num
        for ivr in db.get_ivrs():
            num = str(ivr.get("num") or "").strip()
            if num:
                ivrs[num] = {
                    "name": ivr.get("name") or num,
                    "mappings": {
                        str(item.get("key") or item.get("digit") or "").strip(): {
                            "dest": str(item.get("dest") or "").strip(),
                            "dest_type": str(item.get("dest_type") or "extension").strip()
                        }
                        for item in ivr.get("mappings", [])
                        if str(item.get("key") or item.get("digit") or "").strip()
                    }
                }
    except Exception:
        pass
    return queues, extensions, ivrs

def _active_call_channel_vars(channel):
    safe_channel = str(channel or "").replace('"', '').strip()
    if not safe_channel:
        return {}
    output = run_asterisk_cmd(f"core show channel {safe_channel}")
    vars_found = {}
    for line in output.splitlines():
        line = line.strip()
        if "=" not in line or "RCM_" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("RCM_"):
            vars_found[key] = value.strip()
    return vars_found

def _active_call_group_vars(group):
    merged = {}
    for channel_info in group:
        for key, value in _active_call_channel_vars(channel_info.get("channel", "")).items():
            if value or key not in merged:
                merged[key] = value
    return merged

def _format_named_number(number, names):
    number = str(number or "").strip()
    name = names.get(number)
    if name and name != number:
        return f"{name} ({number})"
    return number

def _display_name_or_number(number, names):
    number = str(number or "").strip()
    return names.get(number) or number

def _queue_number_from_channel(channel_info):
    context = str(channel_info.get("context") or "")
    exten = str(channel_info.get("exten") or "")
    app = str(channel_info.get("app") or "")
    app_data = str(channel_info.get("app_data") or "")
    if app == "Queue":
        return app_data.split(",", 1)[0].strip()
    match = re.match(r"queue-([A-Za-z0-9_-]+)", context)
    if match:
        return match.group(1)
    if exten:
        return exten
    return ""

def _agent_from_group(group, extensions):
    for channel_info in group:
        endpoint = _channel_endpoint(channel_info.get("channel", ""))
        if endpoint in extensions:
            return endpoint
        dialed = _dialed_number_from_app_data(channel_info.get("app_data", ""))
        if dialed in extensions:
            return dialed
    return ""

def _active_call_enriched_destination(group, caller_chan, callee_chan, channel_vars, queues, extensions, ivrs, source_type, caller_source_type=None):
    ivr_num = str(channel_vars.get("RCM_IVR_NUM") or "").strip()
    ivr_digit = str(channel_vars.get("RCM_IVR_DIGIT") or "").strip()
    ivr_info = ivrs.get(ivr_num, {})
    ivr_name = ivr_info.get("name", ivr_num)

    queue_num = ""
    for channel_info in group:
        candidate = _queue_number_from_channel(channel_info)
        if candidate in queues:
            queue_num = candidate
            break

    agent_ext = _agent_from_group(group, extensions)
    if agent_ext and (caller_source_type or source_type) == "trunk":
        agent_label = _display_name_or_number(agent_ext, extensions)
        return agent_label, "agent", ivr_name, _display_name_or_number(queue_num, queues), agent_label

    if queue_num:
        queue_label = _display_name_or_number(queue_num, queues)
        return queue_label, "queue", ivr_name, queue_label, ""

    if ivr_num:
        if ivr_digit:
            mapping = ivr_info.get("mappings", {}).get(ivr_digit, {})
            dest = mapping.get("dest", "")
            dest_type = mapping.get("dest_type", "")
            if dest_type == "queue" and dest in queues:
                queue_label = _display_name_or_number(dest, queues)
                return queue_label, "queue", ivr_name, queue_label, ""
            if dest_type == "extension" and dest in extensions:
                agent_label = _display_name_or_number(dest, extensions)
                return agent_label, "agent", ivr_name, "", agent_label
            return ivr_name, "ivr", ivr_name, "", ""
        return ivr_name, "ivr", ivr_name, "", ""

    dest_num = _active_call_destination(caller_chan, callee_chan)
    if dest_num in queues:
        queue_label = _display_name_or_number(dest_num, queues)
        return queue_label, "queue", "", queue_label, ""
    if dest_num in extensions:
        agent_label = _display_name_or_number(dest_num, extensions)
        return agent_label, "agent", "", "", agent_label
    return dest_num, "", "", "", ""

def get_live_calls_list():
    output = run_asterisk_cmd("core show channels concise")
    raw_channels = []
    if not output:
        return []
    trunks_by_name, trunk_contexts = _active_call_trunk_maps()
    queues_map, extensions_map, ivrs_map = _active_call_display_maps()
        
    for line in output.strip().split('\n'):
        if not line:
            continue
        parts = line.split('!')
        if len(parts) >= 11:
            channel = parts[0]
            context = parts[1]
            exten = parts[2]
            state = parts[4]
            state_lower = state.lower()
            if "up" in state_lower:
                readable_state = "Answered"
            elif "ring" in state_lower:
                readable_state = "Ringing"
            else:
                readable_state = state.capitalize()
                
            caller = parts[7]
            peer_chan = parts[9] if len(parts) > 9 else ""
            
            duration_sec = 0
            try:
                duration_sec = int(parts[10])
            except (ValueError, IndexError):
                pass
                
            linked_id = parts[11] if len(parts) > 11 else ""
            unique_id = parts[12] if len(parts) > 12 else ""
            
            # Clean channel name to extract endpoint
            chan_name_clean = channel.split('/')[1].split('-')[0] if '/' in channel else channel.split('-')[0]
            
            raw_channels.append({
                "channel": channel,
                "clean_name": chan_name_clean,
                "context": context,
                "exten": exten,
                "state": readable_state,
                "caller": caller,
                "peer_channel": peer_chan,
                "duration_sec": duration_sec,
                "linkedid": linked_id,
                "uniqueid": unique_id,
                "app": parts[5] if len(parts) > 5 else "",
                "app_data": parts[6] if len(parts) > 6 else ""
            })
            
    merged_calls = []
    processed_channels = set()
    
    # Group by linkedid
    by_linkedid = {}
    for rc in raw_channels:
        lid = rc["linkedid"]
        if lid:
            if lid not in by_linkedid:
                by_linkedid[lid] = []
            by_linkedid[lid].append(rc)
            
    for lid, group in by_linkedid.items():
        if len(group) >= 2:
            caller_chan = None
            callee_chan = None
            for c in group:
                if c["uniqueid"] == lid:
                    caller_chan = c
                else:
                    callee_chan = c
            
            if not caller_chan:
                dial_chans = [c for c in group if c["app"] == "Dial"]
                if dial_chans:
                    caller_chan = dial_chans[0]
                    callee_chan = [c for c in group if c != caller_chan][0]
                else:
                    caller_chan = group[0]
                    callee_chan = group[1]
                    
            caller_num = _active_call_display_caller(group, caller_chan, trunks_by_name, trunk_contexts, extensions_map)
            dest_num = _active_call_destination(caller_chan, callee_chan)
            
            status = "Ringing"
            if any(c["state"] == "Answered" for c in group):
                status = "Answered"
                
            max_duration = max(c["duration_sec"] for c in group)
            if status != "Answered":
                max_duration = 0
            
            source, source_type = _active_call_group_source(group, caller_chan, trunks_by_name, trunk_contexts)
            _, caller_source_type = _active_call_source(caller_chan, trunks_by_name, trunk_contexts)
            channel_vars = _active_call_group_vars(group)
            dest_label, flow_type, ivr_name, queue_name, agent_name = _active_call_enriched_destination(
                group, caller_chan, callee_chan, channel_vars, queues_map, extensions_map, ivrs_map, source_type, caller_source_type
            )
                
            merged_calls.append({
                "channel": caller_chan["channel"],
                "caller": caller_num,
                "callee": dest_label or dest_num,
                "state": status,
                "duration_sec": max_duration,
                "source": source,
                "trunk_name": source if source_type == "trunk" else "",
                "source_type": source_type,
                "flow_type": flow_type,
                "ivr_name": ivr_name,
                "queue_name": queue_name,
                "agent_name": agent_name,
                "ivr_digit": channel_vars.get("RCM_IVR_DIGIT", "")
            })
            
            for c in group:
                processed_channels.add(c["channel"])
                
    # Single leg channels
    for rc in raw_channels:
        if rc["channel"] in processed_channels:
            continue
            
        caller_num = rc["caller"] or rc["clean_name"]
        dest_num = rc["exten"]
        if not dest_num or dest_num == "s":
            dest_num = rc["app_data"] if rc["app_data"] else rc["app"]
            
        if "PJSIP/" in dest_num:
            m = re.search(r'PJSIP/([A-Za-z0-9_\-]+)', dest_num)
            if m:
                dest_num = m.group(1)
                
        source, source_type = _active_call_source(rc, trunks_by_name, trunk_contexts)
        channel_vars = _active_call_group_vars([rc])
        dest_label, flow_type, ivr_name, queue_name, agent_name = _active_call_enriched_destination(
            [rc], rc, rc, channel_vars, queues_map, extensions_map, ivrs_map, source_type, source_type
        )
            
        merged_calls.append({
            "channel": rc["channel"],
            "caller": caller_num,
            "callee": dest_label or dest_num,
            "state": rc["state"],
            "duration_sec": rc["duration_sec"] if rc["state"] == "Answered" else 0,
            "source": source,
            "trunk_name": source if source_type == "trunk" else "",
            "source_type": source_type,
            "flow_type": flow_type,
            "ivr_name": ivr_name,
            "queue_name": queue_name,
            "agent_name": agent_name,
            "ivr_digit": channel_vars.get("RCM_IVR_DIGIT", "")
        })
        
    for mc in merged_calls:
        dur = mc["duration_sec"]
        mins = dur // 60
        secs = dur % 60
        mc["duration"] = f"{mins:02d}:{secs:02d}"
        
    return merged_calls

def hangup_channel(channel):
    return run_asterisk_cmd(f"channel request hangup {channel}")

def hangup_all():
    return run_asterisk_cmd("channel request hangup all")

# --- Extensions Status ---
def get_pjsip_endpoint_states():
    output = run_asterisk_cmd("pjsip show endpoints")
    states = {}
    if not output:
        return states
    for line in output.splitlines():
        if line.strip().startswith("Endpoint:"):
            subparts = [p.strip() for p in re.split(r'\s{2,}', line.strip()) if p.strip()]
            if len(subparts) >= 2:
                ep_name = subparts[0].replace("Endpoint:", "").strip().split('/')[0]
                state = subparts[1].lower()
                states[ep_name] = state
    return states

def get_pjsip_contacts():
    output = run_asterisk_cmd("pjsip show contacts")
    contacts = {}
    if not output:
        return contacts
    for line in output.splitlines():
        if line.strip().startswith("Contact:"):
            parts = line.split()
            if len(parts) >= 4:
                contact_info = parts[1]
                status = parts[3]
                rtt = parts[4] if len(parts) >= 5 else ""
                if contact_info.startswith('<') or status.startswith('<'):
                    continue
                subparts = contact_info.split('/', 1)
                if len(subparts) == 2:
                    aor = subparts[0]
                    uri = subparts[1]
                    if aor not in contacts:
                        contacts[aor] = []
                    contacts[aor].append({
                        "contact_id": contact_info,
                        "uri": uri,
                        "status": status,
                        "rtt": rtt
                    })
    return contacts

def get_pjsip_registrations():
    output = run_asterisk_cmd("pjsip show registrations")
    regs = {}
    if not output:
        return regs
    for line in output.splitlines():
        line_str = line.strip()
        if line_str.startswith("Registration:"):
            parts = line.split()
            if len(parts) >= 3:
                reg_name = parts[1].split('/')[0]
                state = " ".join(parts[2:])
                regs[reg_name] = state
        elif "/sip:" in line_str and not line_str.startswith("Contact:") and not line_str.startswith("Endpoint:"):
            parts = line.split()
            if len(parts) >= 3 and "/" in parts[0]:
                reg_name = parts[0].split('/')[0]
                state = " ".join(parts[2:])
                regs[reg_name] = state
    return regs

def get_detailed_trunk_status(trunk_type, register_mode, name, contacts_map, reg_map):
    if trunk_type == "peer":
        contacts = contacts_map.get(name, [])
        if not contacts:
            return "Unreachable"
        contact = contacts[0]
        status = str(contact.get("status", "")).strip()
        rtt = contact.get("rtt", "")
        if status == "Avail":
            try:
                rtt_val = float(rtt)
                return f"Reachable ({round(rtt_val)} ms)"
            except Exception:
                return f"Reachable ({rtt} ms)" if rtt else "Reachable"
        elif status == "Unavail":
            return "Unreachable"
        elif status == "NonQual":
            return "Active (No Qualify)"
        else:
            return "Active"
            
    elif trunk_type == "register" and register_mode == "client":
        reg_name = f"{name}-reg"
        reg_state = reg_map.get(reg_name, "")
        if not reg_state:
            reg_state = reg_map.get(name, "")
        reg_state = reg_state.lower()
        
        contacts = contacts_map.get(f"{name}-aor", [])
        if not contacts:
            contacts = contacts_map.get(name, [])
            
        endpoint_status = "Unknown"
        rtt_str = ""
        if contacts:
            c_status = contacts[0]["status"]
            rtt = contacts[0].get("rtt", "")
            if rtt:
                try:
                    rtt_str = f" ({round(float(rtt))} ms)"
                except Exception:
                    rtt_str = f" ({rtt} ms)"
            if c_status == "Avail":
                endpoint_status = "Reachable"
            elif c_status == "Unavail":
                endpoint_status = "Unreachable"
            elif c_status == "NonQual":
                endpoint_status = "Active"
                
        if "registered" in reg_state:
            if endpoint_status == "Unreachable":
                return "Registered (Unreachable)"
            else:
                return f"Registered{rtt_str}"
        elif "rejected" in reg_state or "auth" in reg_state:
            return "Rejected / Auth Failed"
        elif "timeout" in reg_state:
            return "Timeout"
        elif "503" in reg_state or "408" in reg_state or "temp" in reg_state:
            return "Rejected Temporary"
        elif "unregistered" in reg_state or "init" in reg_state:
            return "Unregistered"
        else:
            if endpoint_status == "Reachable":
                return f"Registered{rtt_str}"
            elif endpoint_status == "Unreachable":
                return "Unreachable"
            elif endpoint_status == "Active":
                return "Active"
            return "Unregistered"
            
    elif trunk_type == "register" and register_mode == "server":
        contacts = contacts_map.get(name, [])
        if not contacts:
            return "Unregistered / Expired"
        contact = contacts[0]
        status = contact.get("status", "")
        rtt = contact.get("rtt", "")
        if status == "Avail":
            try:
                rtt_val = float(rtt)
                return f"Registered ({round(rtt_val)} ms)"
            except Exception:
                return "Registered"
        elif status == "Unavail":
            return "Unreachable"
        else:
            return "Unregistered / Expired"
            
    return "Unknown"

def get_extensions_status():
    output = run_asterisk_cmd("pjsip show endpoints")
    status_map = {}
    if not output or "No objects found" in output:
        return status_map
        
    for line in output.split('\n'):
        if line.strip().startswith("Endpoint:"):
            parts = line.split()
            if len(parts) >= 3:
                ext = parts[1].split('/')[0]
                status = parts[2].lower()
                status_map[ext] = "Reachable" if status not in ["unavailable", "unknown"] else "Unreachable"
    return status_map

def get_registered_contacts(target_ext=None):
    # Keep wrapper for compatibility
    contacts = get_pjsip_contacts()
    compat_map = {}
    for ext, ext_contacts in contacts.items():
        if target_ext and str(ext) != str(target_ext):
            continue
        compat_map[ext] = []
        for c in ext_contacts:
            contact_id = c.get("contact_id", "")
            uri = c.get("uri", "")
            user_agent = ""
            via_addr = ""
            
            if contact_id:
                detail_out = run_asterisk_cmd(f"pjsip show contact {contact_id}")
                if detail_out:
                    for line in detail_out.splitlines():
                        if ":" in line:
                            parts = line.split(":", 1)
                            key = parts[0].strip()
                            val = parts[1].strip()
                            if key == "user_agent":
                                user_agent = val
                            elif key == "via_addr":
                                via_addr = val

            clean_ip = ""
            if via_addr and via_addr != "0.0.0.0" and not via_addr.startswith("<"):
                clean_ip = via_addr.split(":")[0].strip()
            else:
                if "@" in uri:
                    ip_part = uri.split("@")[1]
                elif "sip:" in uri:
                    ip_part = uri.split("sip:")[1]
                else:
                    ip_part = uri
                clean_ip = ip_part.split(":")[0].strip()

            brand = "Unknown"
            model = "Unknown"
            if user_agent and user_agent != "-" and user_agent.strip() != "":
                parts = re.split(r'[\s/]+', user_agent.strip())
                brand = parts[0] if len(parts) > 0 else "Unknown"
                model = parts[1] if len(parts) > 1 else "Unknown"

            compat_map[ext].append({
                "ipport": clean_ip,
                "ip": clean_ip,
                "brand": brand,
                "model": model,
                "user_agent": user_agent,
                "status": "Reachable" if c["status"].lower() == "avail" else "Unreachable"
            })
    return compat_map

# --- Trunks Status ---
def get_trunk_status(mode, name):
    contacts_map = get_pjsip_contacts()
    reg_map = get_pjsip_registrations()
    
    trunk_type = "peer"
    register_mode = None
    if mode == "reg-client":
        trunk_type = "register"
        register_mode = "client"
    elif mode == "reg-server":
        trunk_type = "register"
        register_mode = "server"
        
    return get_detailed_trunk_status(trunk_type, register_mode, name, contacts_map, reg_map)

# --- In-place Config Editing ---
@asterisk_config_lock()
def update_section(filepath, section_name, new_keys, remove_keys=None):
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            pass
            
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == f"[{section_name}]":
            start = i
            break
            
    if start is None:
        # Create section at the end
        new_lines = ["", f"[{section_name}]"]
        for k, v in new_keys.items():
            if k == 'rcm_max_contacts':
                new_lines.append(f"; rcm_max_contacts={v}")
            else:
                new_lines.append(f"{k}={v}")
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write("\n".join(new_lines) + "\n")
        return True
        
    for j in range(start + 1, len(lines)):
        if re.match(r'^\[[^\]]+\]$', lines[j].strip()):
            end = j
            break
            
    body = lines[start + 1:end]
    new_body = []
    keys_written = set()
    
    for line in body:
        t = line.strip()
        if t.startswith(';') or not t:
            if t.startswith(';'):
                m = re.match(r'^;\s*([A-Za-z0-9_\-]+)\s*=\s*(.+)$', t)
                if m and m.group(1) == "rcm_max_contacts":
                    key = m.group(1)
                    if key in new_keys:
                        new_body.append(f"; {key}={new_keys[key]}")
                        keys_written.add(key)
                        continue
            new_body.append(line)
            continue
            
        if '=' in t:
            k, v = [x.strip() for x in t.split('=', 1)]
            if remove_keys and k in remove_keys:
                continue
            if k in new_keys:
                if k in keys_written:
                    continue
                new_body.append(f"{k}={new_keys[k]}")
                keys_written.add(k)
            else:
                new_body.append(line)
        else:
            new_body.append(line)
            
    for k, v in new_keys.items():
        if k not in keys_written:
            if k == 'rcm_max_contacts':
                new_body.append(f"; rcm_max_contacts={v}")
            else:
                new_body.append(f"{k}={v}")
                
    # Ensure disallow= always comes before allow= for Asterisk PJSIP codec rules
    disallows = [l for l in new_body if l.strip().startswith('disallow=')]
    allows = [l for l in new_body if l.strip().startswith('allow=')]
    others = [l for l in new_body if not l.strip().startswith('disallow=') and not l.strip().startswith('allow=')]
    if disallows or allows:
        new_body = others + disallows + allows

    out = lines[:start + 1] + new_body + lines[end:]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(out) + "\n")
    return True

@asterisk_config_lock()
def delete_section(filepath, section_name):
    if not os.path.exists(filepath):
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == f"[{section_name}]":
            start = i
            break
            
    if start is not None:
        for j in range(start + 1, len(lines)):
            if re.match(r'^\[[^\]]+\]$', lines[j].strip()):
                end = j
                break
        lines = lines[:start] + lines[end:]
        
    collapsed = []
    prev_blank = False
    for line in lines:
        if line.strip() == "":
            if not prev_blank:
                collapsed.append(line)
                prev_blank = True
        else:
            collapsed.append(line)
            prev_blank = False
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(collapsed) + "\n")

# --- Extensions Configurations Sync ---
def write_extension_configs(data, reload=True):
    ext = str(data["ext"]).strip()
    enabled = bool(data["enabled"])
    secret = str(data["secret"]).strip()
    name = str(data["name"]).strip()
    callerid_number = str(data["callerid_number"]).strip()
    max_contacts = int(data["max_contacts"])
    max_expiration = int(data["max_expiration"])
    ring_time = int(data["ring_time"])
    record_mode = normalize_record_mode(data.get("record_mode", "noo"))
    dtmf_mode = str(data.get("dtmf_mode", "rfc4733") or "rfc4733").strip()
    if dtmf_mode not in ALLOWED_DTMF_MODES:
        dtmf_mode = "rfc4733"
    moh_class = str(data.get("moh_class", "default") or "default").strip()
    if not re.match(r'^[A-Za-z0-9_.-]+$', moh_class):
        moh_class = "default"
    vm_enabled = bool(data["vm_enabled"])
    vm_password = str(data["vm_password"]).strip()
    direct_media = bool(data["direct_media"])
    nat = bool(data["nat"])
    codecs = normalize_extension_codecs(data.get("codecs", "alaw,ulaw"))
    video_support = bool(data.get("video_support", False))
    endpoint_codecs = codecs
    
    followme = data.get("followme", [])
    followme_enabled = "on" if followme else "off"

    # 1. pjsip.gui.endpoint.conf
    cid_str = f'"{name}" <{callerid_number}>' if name else callerid_number
    new_ep_keys = {
        "type": "endpoint",
        "context": f"from-internal-{ext}",
        "callerid": cid_str,
        "disallow": "all",
        "allow": endpoint_codecs,
        "aors": ext,
        "auth": ext,
        "transport": "transport-udp",
        "dtmf_mode": dtmf_mode,
        "max_video_streams": 1 if video_support else 0,
        "moh_suggest": moh_class,
        "direct_media": "yes" if direct_media else "no"
    }
    remove_ep_keys = ["named_call_group", "named_pickup_group", "named_call_pickup_group"]
    if nat:
        new_ep_keys["rtp_symmetric"] = "yes"
        new_ep_keys["rewrite_contact"] = "yes"
        new_ep_keys["force_rport"] = "yes"
    else:
        remove_ep_keys.extend(["rtp_symmetric", "rewrite_contact", "force_rport"])

    try:
        import db
        pgs = db.get_pickup_groups()
        my_gids = [str(pg.get('id') or pg.get('num')) for pg in pgs if str(ext) in [str(m).strip() for m in pg.get("members", [])] and (pg.get("id") or pg.get("num"))]
        if my_gids:
            my_numeric = [gid for gid in my_gids if gid.isdigit() and int(gid) <= 63]
            if my_numeric:
                new_ep_keys["call_group"] = ",".join(my_numeric)
                new_ep_keys["pickup_group"] = ",".join(my_numeric)
            else:
                remove_ep_keys.extend(["call_group", "pickup_group"])
        else:
            remove_ep_keys.extend(["named_call_group", "named_pickup_group", "call_group", "pickup_group", "named_call_pickup_group"])
    except Exception:
        pass

    update_section(EP_FILE, ext, new_ep_keys, remove_ep_keys)

    # 2. pjsip.gui.auth.conf
    new_auth_keys = {
        "type": "auth",
        "auth_type": "userpass",
        "username": ext,
        "password": secret
    }
    update_section(AUTH_FILE, ext, new_auth_keys)

    # 3. pjsip.gui.aor.conf
    actual_max = max_contacts if enabled else 0
    new_aor_keys = {
        "type": "aor",
        "rcm_max_contacts": str(max_contacts),
        "max_contacts": str(actual_max),
        "remove_existing": "yes",
        "qualify_frequency": "60",
        "maximum_expiration": str(max_expiration)
    }
    update_section(AOR_FILE, ext, new_aor_keys)

    # 4. extensions_gui.conf globals & internal dialplan
    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            dp_lines = f.read().splitlines()
    else:
        dp_lines = ["[globals]", "", "[internal]"]

    # Remove existing global variables and extension routing line
    new_dp_lines = []
    for line in dp_lines:
        t = line.strip()
        if t.startswith(f"RECORD_{ext}=") or t.startswith(f"VM_{ext}=") or t.startswith(f"RING_{ext}=") or t.startswith(f"FM_{ext}=") or t.startswith(f"exten => {ext},"):
            continue
        new_dp_lines.append(line)

    # Re-insert globals and internal routing
    final_dp_lines = []
    globals_inserted = False
    internal_inserted = False
    for line in new_dp_lines:
        final_dp_lines.append(line)
        if line.strip() == "[globals]" and not globals_inserted:
            final_dp_lines.append(f"RECORD_{ext}={record_mode}")
            final_dp_lines.append(f"VM_{ext}={'On' if vm_enabled else 'Off'}")
            final_dp_lines.append(f"RING_{ext}={ring_time}")
            final_dp_lines.append(f"FM_{ext}={followme_enabled}")
            globals_inserted = True
        if line.strip() == "[internal]" and not internal_inserted:
            final_dp_lines.append(f"exten => {ext},1,Goto(dexter,${{EXTEN}},1)")
            internal_inserted = True

    if not globals_inserted:
        final_dp_lines.extend(["", "[globals]", f"RECORD_{ext}={record_mode}", f"VM_{ext}={'On' if vm_enabled else 'Off'}", f"RING_{ext}={ring_time}", f"FM_{ext}={followme_enabled}"])
    if not internal_inserted:
        final_dp_lines.extend(["", "[internal]", f"exten => {ext},1,Goto(dexter,${{EXTEN}},1)"])

    # Clean double blank lines
    cleaned = []
    prev_blank = False
    for line in final_dp_lines:
        if line.strip() == "":
            if not prev_blank:
                cleaned.append(line)
                prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    with open(DP_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(cleaned) + "\n")

    ensure_recording_context_file(DP_FILE)
    sync_legacy_recording_policy()

    # 5. context_exten.conf per-extension context
    if reload:
        try:
            routes_data = db.get_outbound_routes()
        except Exception:
            routes_data = []
        rebuild_all_extensions_contexts(routes_data)

    # 6. voicemail.conf
    vm_display_name = name if name else ext
    vm_line = f"{ext} => {vm_password},{vm_display_name},,,"
    if os.path.exists(VM_FILE):
        with open(VM_FILE, 'r', encoding='utf-8') as f:
            vm_lines = f.read().splitlines()
    else:
        vm_lines = ["[general]", "", "[default]"]

    new_vm_lines = []
    in_default = False
    vm_inserted = False
    for line in vm_lines:
        t = line.strip()
        if t.startswith('[') and t.endswith(']'):
            if in_default and not vm_inserted and vm_enabled:
                new_vm_lines.append(vm_line)
                vm_inserted = True
            in_default = (t.lower() == '[default]')
            new_vm_lines.append(line)
            continue
        if in_default and re.match(r'^' + ext + r'\s*=>', t):
            if vm_enabled:
                new_vm_lines.append(vm_line)
                vm_inserted = True
            else:
                continue
        else:
            new_vm_lines.append(line)
    if in_default and not vm_inserted and vm_enabled:
        new_vm_lines.append(vm_line)
    with open(VM_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_vm_lines) + "\n")

    # 7. followme.conf
    delete_section(FM_FILE, ext)
    if followme:
        fm_block = f"\n[{ext}]\ncontext => internal\n"
        for row in followme:
            fnum = str(row.get("number", "")).strip()
            fring = int(row.get("ring", 15))
            if fnum:
                fm_block += f"number => {fnum},{fring}\n"
        with open(FM_FILE, 'a', encoding='utf-8') as f:
            f.write(fm_block + "\n")

    # Reload
    apply_extension_runtime_flags(ext, data)
    if reload:
        run_asterisk_cmd("pjsip reload")
        run_asterisk_cmd("dialplan reload")
        run_asterisk_cmd("module reload app_followme.so")
        run_asterisk_cmd("module reload app_voicemail.so")

def delete_extension_configs(ext, reload=True):
    delete_section(EP_FILE, ext)
    delete_section(AUTH_FILE, ext)
    delete_section(AOR_FILE, ext)

    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            dp_lines = f.read().splitlines()
        new_dp_lines = []
        for line in dp_lines:
            t = line.strip()
            if t.startswith(f"RECORD_{ext}=") or t.startswith(f"VM_{ext}=") or t.startswith(f"RING_{ext}=") or t.startswith(f"FM_{ext}=") or t.startswith(f"exten => {ext},"):
                continue
            new_dp_lines.append(line)
        with open(DP_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_dp_lines) + "\n")
        ensure_recording_context_file(DP_FILE)

    delete_section(CTX_FILE, f"from-internal-{ext}")
    
    # voicemail
    if os.path.exists(VM_FILE):
        with open(VM_FILE, 'r', encoding='utf-8') as f:
            vm_lines = f.read().splitlines()
        new_vm_lines = []
        in_default = False
        for line in vm_lines:
            t = line.strip()
            if t.startswith('[') and t.endswith(']'):
                in_default = (t.lower() == '[default]')
                new_vm_lines.append(line)
                continue
            if in_default and re.match(r'^' + ext + r'\s*=>', t):
                continue
            new_vm_lines.append(line)
        with open(VM_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_vm_lines) + "\n")

    # followme
    delete_section(FM_FILE, ext)
    apply_extension_features(ext, {"always": "", "noanswer": "", "busy": "", "dnd": "off"})
    astdb_delete_if_exists("SPY/DENY", ext)

    # Reload
    if reload:
        run_asterisk_cmd("pjsip reload")
        run_asterisk_cmd("dialplan reload")
        run_asterisk_cmd("module reload app_followme.so")
        run_asterisk_cmd("module reload app_voicemail.so")

# --- Trunks Configurations Sync ---
@asterisk_config_lock()
def upsert_trunk_block(filepath, trunk_name, block_content):
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            pass
            
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    begin_marker = f"; --- RCM-TRUNK: {trunk_name} BEGIN ---"
    end_marker = f"; --- RCM-TRUNK: {trunk_name} END ---"
    
    new_block = f"{begin_marker}\n{block_content.strip()}\n{end_marker}\n"
    
    pattern = re.compile(r'^\s*;\s*---\s*RCM-TRUNK:\s*' + re.escape(trunk_name) + r'\s*BEGIN\s*---\s*$.*?^\s*;\s*---\s*RCM-TRUNK:\s*' + re.escape(trunk_name) + r'\s*END\s*---\s*$', re.MULTILINE | re.DOTALL)
    
    if pattern.search(content):
        content = pattern.sub(new_block, content, count=1)
    else:
        content = content.rstrip() + "\n\n" + new_block
        
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

@asterisk_config_lock()
def delete_trunk_block(filepath, trunk_name):
    if not os.path.exists(filepath):
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    pattern = re.compile(r'^\s*;\s*---\s*RCM-TRUNK:\s*' + re.escape(trunk_name) + r'\s*BEGIN\s*---\s*$.*?^\s*;\s*---\s*RCM-TRUNK:\s*' + re.escape(trunk_name) + r'\s*END\s*---\s*$\s*', re.MULTILINE | re.DOTALL)
    
    if pattern.search(content):
        content = pattern.sub('', content)
        content = re.sub(r'\n{4,}', '\n\n\n', content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

def write_trunk_configs(data):
    name = str(data["name"]).strip()
    enabled = bool(data["enabled"])
    type_ = str(data["type"]).strip()
    reg_mode = str(data.get("register_mode", "") or "").strip()
    server = str(data.get("server_addr", "") or "").strip()
    port = int(data["server_port"]) if data.get("server_port") else 5060
    keepalive = int(data["keepalive"]) if data.get("keepalive") else 60
    transport = str(data.get("transport", "transport-udp")).strip()
    outproxy_addr = str(data.get("outproxy_addr", "") or "").strip()
    outproxy_port = int(data["outproxy_port"]) if data.get("outproxy_port") else 0
    password = str(data.get("password", "") or "").strip()
    username = str(data.get("username", "") or "").strip()
    auth_id = str(data.get("auth_id", "") or "").strip()
    from_user = str(data.get("from_user", "") or "").strip()
    from_domain = str(data.get("from_domain", "") or "").strip()
    identify_by = str(data.get("identify_by", "username")).strip()

    # New Dynamic Properties
    context = str(data.get("context", "from-trunk")).strip()
    codecs = str(data.get("codecs", "ulaw,alaw")).strip()
    allowed_ip = str(data.get("allowed_ip", "") or "").strip()
    caller_id = str(data.get("caller_id", "") or "").strip()
    qualify = int(data.get("qualify", 1))
    nat = bool(data.get("nat", 0))
    max_expiration = int(data.get("max_expiration", 3600) or 3600)

    if not enabled:
        delete_trunk_configs(name)
        return

    # Build blocks
    ep_block = ""
    aor_block = ""
    auth_block = ""
    reg_block = ""
    id_block = ""

    qualify_freq = keepalive if qualify else 0

    if type_ == "peer":
        ep_lines = [
            f"[{name}]",
            "type=endpoint",
            f"transport={transport}",
            f"context={context}",
            "disallow=all",
            f"allow={codecs}",
            f"aors={name}",
            "direct_media=no"
        ]
        if caller_id:
            ep_lines.append(f"callerid={caller_id}")
        if nat:
            ep_lines.extend(["rtp_symmetric=yes", "rewrite_contact=yes", "force_rport=yes"])
        if any(v in codecs.lower() for v in ["h264", "h263", "vp8", "vp9"]):

            ep_lines.append("max_video_streams=1")

        ep_block = "\n".join(ep_lines) + "\n"


        aor_block = f"""
[{name}]
type=aor
contact=sip:{server}:{port}
qualify_frequency={qualify_freq}
maximum_expiration={max_expiration}
"""
        id_block = f"""
[{name}_identify]
type=identify
endpoint={name}
match={server}
"""
    elif type_ == "register" and reg_mode == "client":
        ep_lines = [
            f"[{name}]",
            "type=endpoint",
            f"transport={transport}",
            f"context={context}",
            "disallow=all",
            f"allow={codecs}",
            f"aors={name}-aor",
            f"outbound_auth={name}-auth",
            f"identify_by={identify_by}",
            "direct_media=no"
        ]
        if from_user:
            ep_lines.append(f"from_user={from_user}")
        if from_domain:
            ep_lines.append(f"from_domain={from_domain}")
        if outproxy_addr:
            if outproxy_port:
                ep_lines.append(f"outbound_proxy=sip:{outproxy_addr}:{outproxy_port}\\;lr")
            else:
                ep_lines.append(f"outbound_proxy=sip:{outproxy_addr}\\;lr")
        if caller_id:
            ep_lines.append(f"callerid={caller_id}")
        if nat:
            ep_lines.extend(["rtp_symmetric=yes", "rewrite_contact=yes", "force_rport=yes"])
        if any(v in codecs.lower() for v in ["h264", "h263", "vp8", "vp9"]):

            ep_lines.append("max_video_streams=1")

        ep_block = "\n".join(ep_lines) + "\n"


        auth_block = f"""
[{name}-auth]
type=auth
auth_type=userpass
username={auth_id}
password={password}
"""
        aor_block = f"""
[{name}-aor]
type=aor
contact=sip:{username}@{server}:{port}
qualify_frequency={qualify_freq}
maximum_expiration={max_expiration}
"""
        id_block = f"""
[{name}-identify]
type=identify
endpoint={name}
match={server}
"""
        # Optional reg features
        reg_lines = [
            f"[{name}-reg]",
            "type=registration",
            f"outbound_auth={name}-auth",
            f"server_uri=sip:{server}:{port}",
            f"client_uri=sip:{username}@{server}",
            "expiration=3600"
        ]
        if from_user:
            reg_lines.append(f"from_user={from_user}")
        if from_domain:
            reg_lines.append(f"from_domain={from_domain}")
        if outproxy_addr:
            if outproxy_port:
                reg_lines.append(f"outbound_proxy=sip:{outproxy_addr}:{outproxy_port}\\;lr")
            else:
                reg_lines.append(f"outbound_proxy=sip:{outproxy_addr}\\;lr")
            
        reg_block = "\n".join(reg_lines) + "\n"

    elif type_ == "register" and reg_mode == "server":
        ep_lines = [
            f"[{name}]",
            "type=endpoint",
            f"transport={transport}",
            f"context={context}",
            "disallow=all",
            f"allow={codecs}",
            f"aors={name}",
            f"auth={name}-auth",
            f"outbound_auth={name}-auth",
            "rewrite_contact=yes",
            "direct_media=no"
        ]
        if caller_id:
            ep_lines.append(f"callerid={caller_id}")
        if nat:
            ep_lines.extend(["rtp_symmetric=yes", "force_rport=yes"])
        if any(v in codecs.lower() for v in ["h264", "h263", "vp8", "vp9"]):

            ep_lines.append("max_video_streams=1")

        ep_block = "\n".join(ep_lines) + "\n"


        aor_block = f"""
[{name}]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency={qualify_freq}
maximum_expiration={max_expiration}
"""
        auth_block = f"""
[{name}-auth]
type=auth
auth_type=userpass
username={name}
password={password}
"""
        if allowed_ip:
            id_block = f"""
[{name}_identify]
type=identify
endpoint={name}
match={allowed_ip}
"""

    # Upsert/Write blocks
    upsert_trunk_block(EP_FILE, name, ep_block)
    upsert_trunk_block(AOR_FILE, name, aor_block)
    
    if auth_block:
        upsert_trunk_block(AUTH_FILE, name, auth_block)
    else:
        delete_trunk_block(AUTH_FILE, name)
        
    if reg_block:
        upsert_trunk_block(REG_FILE, name, reg_block)
    else:
        delete_trunk_block(REG_FILE, name)
        
    if id_block:
        upsert_trunk_block(IDENTIFY_FILE, name, id_block)
    else:
        delete_trunk_block(IDENTIFY_FILE, name)

    # Reload
    run_asterisk_cmd("pjsip reload")

def delete_trunk_configs(name):
    delete_trunk_block(EP_FILE, name)
    delete_trunk_block(AOR_FILE, name)
    delete_trunk_block(AUTH_FILE, name)
    delete_trunk_block(REG_FILE, name)
    delete_trunk_block(IDENTIFY_FILE, name)
    
    # Reload
    run_asterisk_cmd("pjsip reload")

# --- Audio File Converter ---
import shutil
import subprocess

def save_and_convert_audio(src_path, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if shutil.which("sox"):
        cmd = ["sox", src_path, "-r", "8000", "-c", "1", "-b", "16", "-e", "signed-integer", dest_path]
        try:
            subprocess.run(cmd, check=True)
            return os.path.exists(dest_path) and os.path.getsize(dest_path) > 44
        except Exception:
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            pass

    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-i", src_path, "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", dest_path]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return os.path.exists(dest_path) and os.path.getsize(dest_path) > 44
        except Exception:
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            pass

    return False

# --- Call Routing Dialplan Sync Helpers ---
def resolve_asterisk_prompt(prompt_id):
    if not prompt_id:
        return "silence/1"
    db_path = "/etc/asterisk/rcm_media_center.json"
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                db = json.load(f)
            for p in db.get("prompts", []):
                if p.get("id") == prompt_id:
                    path = p.get("path", "")
                    for prefix in ["/var/lib/asterisk/sounds/en/", "/var/lib/asterisk/sounds/"]:
                        if path.startswith(prefix):
                            path = path[len(prefix):]
                    path = os.path.splitext(path)[0]
                    return path
        except Exception:
            pass
    return "silence/1"

def resolve_dest_to_dialplan(dest_type, dest_val):
    if dest_type in ("internal", "callee") or dest_val in ("__INBOUND_CALLEE__", "${EXTEN}", "${DID}"):
        if not dest_val or dest_val in ("__INBOUND_CALLEE__", "${EXTEN}", "${DID}"):
            return "Goto(internal,${DID},1)"
        return f"Goto(internal,{dest_val},1)"
    if not dest_type or dest_type == "hangup" or not dest_val:
        return "Hangup()"
    if dest_type == "voicemail":
        return f"Voicemail({dest_val}@default,b)"
    if dest_type == "ivr":
        return f"Goto(ivr-{dest_val},{dest_val},1)"
    if dest_type == "queue":
        return f"Goto(queue-{dest_val},{dest_val},1)"
    if dest_type == "announcement":
        return f"Goto(ann-{dest_val},{dest_val},1)"
    if dest_type == "ringgroup":
        return f"Goto(rcm-ring-groups,{dest_val},1)"
    if dest_type == "paging":
        return f"Goto(rcm-paging-intercom,{dest_val},1)"
    if dest_type == "conference":
        return f"Goto(rcm-conferences,{dest_val},1)"
    if dest_type == "featurecode":
        return f"Goto(rcm-feature-codes,{dest_val},1)"
    if dest_type in ["external", "other"]:
        phone_num = str(dest_val).strip()
        perm_ctx = "from-internal-inbound"
        if "|" in phone_num:
            parts = phone_num.split("|", 1)
            phone_num = parts[0].strip()
            perm_tag = parts[1].strip()
            if perm_tag.startswith("ext:"):
                ext_id = perm_tag.split(":", 1)[1].strip()
                perm_ctx = f"from-internal-{ext_id}"
        return f"Goto({perm_ctx},{phone_num},1)"
    return f"Goto(internal,{dest_val},1)"

def sync_ivr_dialplan(ivrs):
    def enabled(value):
        return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")

    lines = ["; IVR Dialplan Generated by RCM", ""]
    lines.append("[rcm-ivr-routes]")
    for ivr in ivrs:
        num = ivr.get("num")
        if num:
            lines.append(f"exten => {num},1,Goto(ivr-{num},{num},1)")
    lines.append("")
    
    for ivr in ivrs:
        num = ivr.get("num")
        name = ivr.get("name", "")
        prompt_id = ivr.get("prompt_id")
        response_timeout_prompt = ivr.get("response_timeout_prompt")
        invalid_input_prompt = ivr.get("invalid_input_prompt")
        timeout = ivr.get("timeout", 10)
        digit_timeout = max(_safe_int(ivr.get("digit_timeout", 3), 3), 1)
        loops = int(ivr.get("loops", 3))
        fail_mode = ivr.get("fail_mode", "hangup")
        fail_ext = ivr.get("fail_ext", "")
        mappings = ivr.get("mappings", [])
        ultra_numbers = ivr.get("ultra_numbers", [])
        dial_extension = enabled(ivr.get("dial_extension", False))
        replace_display_name = enabled(ivr.get("replace_display_name", False))
        auto_record = enabled(ivr.get("auto_record", False))

        if not num:
            continue

        prompt_path = resolve_asterisk_prompt(prompt_id)
        response_timeout_path = resolve_asterisk_prompt(response_timeout_prompt) if response_timeout_prompt else ""
        invalid_input_path = resolve_asterisk_prompt(invalid_input_prompt) if invalid_input_prompt else ""
        limit = loops + 1
        safe_name = re.sub(r'[,)"\\\r\n]', "_", str(name or num))
        # Keep a compact delimiter-safe journey value in CDR(userfield).
        safe_path_name = re.sub(r'[~|:;=,"\r\n]', "_", str(name or num)).strip() or str(num)

        fail_type = "extension" if fail_mode == "goto" else fail_mode
        fail_action = resolve_dest_to_dialplan(fail_type, fail_ext)
        if fail_type == "hangup" or not fail_action or fail_action == "Hangup()":
            fail_action = "Playback(goodbye)\n same => n,Hangup()"

        lines.append(f"; --- IVR GUI: {name} ---")
        lines.append(f"[ivr-{num}]")
        lines.append(f"exten => {num},1,Answer()")
        lines.append(f" same => n,Set(__RCM_IVR_NUM={num})")
        lines.append(f" same => n,Set(__RCM_IVR_NAME={safe_name})")
        lines.append(" same => n,Set(__RCM_IVR_DIGIT=)")
        lines.append(" same => n,Set(__RCM_IVR_DEST_TYPE=)")
        lines.append(" same => n,Set(__RCM_IVR_DEST=)")
        lines.append(f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~IVR:{num}:{safe_path_name})")
        lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
        if replace_display_name:
            lines.append(f" same => n,Set(CALLERID(name)={safe_name})")
        if auto_record:
            lines.append(f" same => n,Set(CALLFILENAME=ivr-{num}-${{CALLERID(num)}}-${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}})")
            lines.extend(recording_trigger_lines())
        lines.append(f" same => n,Set(TIMEOUT(digit)={digit_timeout})")
        lines.append(" same => n,Mset(test=1,cuc=1)")
        lines.append(f" same => n(start),Background({prompt_path})")
        lines.append(f" same => n,WaitExten({timeout})")
        lines.append("")

        for m in mappings:
            key = m.get("key")
            dest = m.get("dest")
            dest_type = m.get("dest_type", "extension")
            if key and dest:
                dest_action = resolve_dest_to_dialplan(dest_type, dest)
                lines.append(f"exten => {key},1,Set(__RCM_IVR_DIGIT={key})")
                lines.append(f" same => n,Set(__RCM_IVR_DEST_TYPE={dest_type})")
                lines.append(f" same => n,Set(__RCM_IVR_DEST={dest})")
                safe_dest = re.sub(r'[~|:;=,"\r\n]', "_", str(dest)).strip()
                lines.append(f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~DIGIT:{key}~DEST:{dest_type}:{safe_dest})")
                lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
                lines.append(f" same => n,{dest_action}")

        for ultra in ultra_numbers:
            number = str(ultra.get("number") or "").strip()
            dest = str(ultra.get("dest") or "").strip()
            dest_type = ultra.get("dest_type", "extension")
            if number and dest and re.fullmatch(r"[0-9*#]+", number):
                dest_action = resolve_dest_to_dialplan(dest_type, dest)
                lines.append(f"exten => {number},1,Set(__RCM_IVR_DIGIT={number})")
                lines.append(f" same => n,Set(__RCM_IVR_DEST_TYPE={dest_type})")
                lines.append(f" same => n,Set(__RCM_IVR_DEST={dest})")
                safe_dest = re.sub(r'[~|:;=,"\r\n]', "_", str(dest)).strip()
                lines.append(f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~DIGIT:{number}~DEST:{dest_type}:{safe_dest})")
                lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
                lines.append(f" same => n,{dest_action}")

        if dial_extension:
            lines.append("include => internal")
        
        lines.append("")
        lines.append("exten => i,1,Set(test=$[${test} + 1])")
        if invalid_input_path:
            lines.append(f" same => n,Playback({invalid_input_path})")
        lines.append(f" same => n,GotoIf($[${{test}} < {limit}]?{num},start)")
        lines.append(f" same => n,{fail_action}")
        lines.append("exten => t,1,Set(cuc=$[${cuc} + 1])")
        if response_timeout_path:
            lines.append(f" same => n,Playback({response_timeout_path})")
        lines.append(f" same => n,GotoIf($[${{cuc}} < {limit}]?{num},start)")
        lines.append(f" same => n,{fail_action}")
        lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.ivr.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
    run_asterisk_cmd("dialplan reload")

def sync_ringgroup_dialplan(groups):
    lines = ["; Ring Groups Dialplan Generated by RCM", ""]


    lines.append("[rcm-ring-groups]")
    for g in groups:
        gid = g.get("id")
        name = g.get("name", "")
        strat = g.get("strategy", "ringall")
        timeout = g.get("timeout", 20)
        per_try = g.get("per_try", 10)
        failover = g.get("failover", "")
        failover_type = g.get("failover_type", "extension") if g.get("failover_value") else "hangup"
        failover_val = g.get("failover_value") or failover
        members = g.get("members", [])

        if not gid or not members:
            continue

        pre_ring = g.get("pre_ring_announcement")
        fail_action = resolve_dest_to_dialplan(failover_type, failover_val)
        safe_path_name = re.sub(r'[~|:;=,"\r\n]', "_", str(name or gid)).strip() or str(gid)
        path_lines = [
            f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~RINGGROUP:{gid}:{safe_path_name})",
            " same => n,Set(CDR(userfield)=${RCM_CALL_PATH})",
        ]
        record_lines = [
            ' same => n,GotoIf($["${RECORD_${CALLERID(num)}}"="out" | "${RECORD_${CALLERID(num)}}"="all"]?rcm_rg_record)',
        ]
        for member in members:
            member = str(member).strip()
            if not re.fullmatch(r"[0-9A-Za-z_.-]+", member):
                continue
            record_lines.append(
                f' same => n,GotoIf($["${{RECORD_{member}}}"="in" | "${{RECORD_{member}}}"="all"]?rcm_rg_record)'
            )
        record_lines.extend([
            " same => n,Goto(rcm_rg_record_continue)",
            f" same => n(rcm_rg_record),Set(CALLFILENAME=ringgroup-{gid}-${{CALLERID(num)}}-${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}})",
        ])
        record_lines.extend(recording_trigger_lines())
        record_lines.append(" same => n(rcm_rg_record_continue),NoOp(RCM ring group recording policy checked)")

        if pre_ring:
            prompt_path = resolve_asterisk_prompt(pre_ring)
            lines.append(f"exten => {gid},1,Answer()")
            lines.append(f" same => n,Playback({prompt_path})")
            lines.append(f" same => n,NoOp(RCM-RG id={gid} name={name} strategy={strat})")
            lines.extend(path_lines)
            lines.extend(record_lines)
            if strat == "ringall":
                dial_str = "&".join([f"PJSIP/{m}" for m in members])
                lines.append(f" same => n,Dial({dial_str},{timeout},Tt)")
                lines.append(f" same => n,{fail_action}")
            else:
                for m in members:
                    lines.append(f" same => n,Dial(PJSIP/{m},{per_try},Tt)")
                    lines.append(" same => n,GotoIf($[\"${DIALSTATUS}\"=\"ANSWER\"]?done)")
                lines.append(f" same => n(done),{fail_action}")
        else:
            lines.extend(path_lines)
            lines.extend(record_lines)
            if strat == "ringall":
                dial_str = "&".join([f"PJSIP/{m}" for m in members])
                lines.append(f"exten => {gid},1,Dial({dial_str},{timeout},Tt)")
                lines.append(f" same => n,{fail_action}")
            else:
                first = True
                for m in members:
                    if first:
                        lines.append(f"exten => {gid},1,Dial(PJSIP/{m},{per_try},Tt)")
                        first = False
                    else:
                        lines.append(f" same => n,Dial(PJSIP/{m},{per_try},Tt)")
                    lines.append(" same => n,GotoIf($[\"${DIALSTATUS}\"=\"ANSWER\"]?done)")
                lines.append(f" same => n(done),{fail_action}")
        lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.ringgroup.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)

    # A Ring Group based outbound permission is resolved to the group's
    # current members when the per-extension contexts are generated.  Keep
    # that derived dialplan in sync whenever membership changes; otherwise a
    # newly added member would only receive the permission after an unrelated
    # outbound-route edit.
    try:
        import db
        rebuild_all_extensions_contexts(db.get_outbound_routes())
    except Exception as exc:
        # Preserve the existing Ring Group update even if the Asterisk files
        # are temporarily unavailable. The normal sync warning/retry path can
        # report the file-system problem without losing the database change.
        print(f"Ring Group outbound-permission context sync failed: {exc}")

    run_asterisk_cmd("dialplan reload")

def sync_paging_dialplan(items):
    lines = ["; Paging & Intercom Dialplan Generated by RCM", ""]

    def safe_paging_ext(value):
        value = str(value or "").strip()
        return value if re.fullmatch(r"[0-9*#]+", value) else ""

    def safe_caller(value):
        value = str(value or "").strip()
        return value if re.fullmatch(r"[0-9*#+]+", value) else ""

    def safe_endpoint(value):
        value = str(value or "").strip()
        return value if re.fullmatch(r"[A-Za-z0-9_.-]+", value) else ""

    def safe_comment(value):
        return str(value or "").replace("\r", " ").replace("\n", " ").strip()

    enabled_items = []
    for item in items or []:
        if not item.get("enabled", True):
            continue
        pid = safe_paging_ext(item.get("id"))
        members = [safe_endpoint(m) for m in item.get("members", [])]
        members = [m for m in members if m]
        if not pid or not members:
            print(f"Invalid paging item skipped: {item}")
            return False
        enabled_items.append((item, pid, members))

    lines.append("[internal](+)")
    for item, pid, members in enabled_items:
        lines.append(f"exten => {pid},1,Goto(rcm-paging-intercom,${{EXTEN}},1)")
    lines.append("")

    lines.append("[rcm-paging-intercom]")
    for item, pid, members in enabled_items:
        name = safe_comment(item.get("name", ""))
        welcome_prompt = item.get("welcome_prompt", "")
        allowed = [safe_caller(c) for c in item.get("allowed_callers", [])]
        allowed = [c for c in allowed if c]
        duplex = item.get("duplex", False)

        targets = "&".join([f"PJSIP/{m}" for m in members])
        prompt_path = resolve_asterisk_prompt(welcome_prompt) if welcome_prompt else safe_comment(item.get("legacy_prompt_path", ""))
        if prompt_path and prompt_path != "silence/1":
            exists = False
            prefixes = ["/var/lib/asterisk/sounds/en/", "/var/lib/asterisk/sounds/"]
            if prompt_path.startswith("/"):
                prefixes = [""]
            for pfx in prefixes:
                for ext in [".wav", ".alaw", ".ulaw", ".gsm", ".sln", ".sln16"]:
                    if os.path.exists(f"{pfx}{prompt_path}{ext}"):
                        exists = True
                        break
                if exists:
                    break
            if not exists:
                prompt_path = ""
        elif prompt_path == "silence/1":
            prompt_path = ""

        lines.append(f"; {name}")
        lines.append(f"exten => {pid},1,NoOp(RCM Paging for {name})")
        safe_path_name = re.sub(r'[~|:;=,"\r\n]', "_", str(name or pid)).strip() or pid
        path_kind = "INTERCOM" if duplex else "PAGING"
        lines.append(f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~{path_kind}:{pid}:{safe_path_name})")
        lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")

        if allowed:
            for caller in allowed:
                lines.append(f" same => n,GotoIf($[\"{caller}\"=\"${{CALLERID(num)}}\"]?allow)")
            lines.append(" same => n,Hangup()")
            lines.append(" same => n(allow),NoOp(Caller allowed)")
        else:
            lines.append(" same => n(allow),NoOp(Any caller allowed)")

        lines.append(' same => n,GotoIf($["${RECORD_${CALLERID(num)}}"="out" | "${RECORD_${CALLERID(num)}}"="all"]?rcm_page_record)')
        for member in members:
            lines.append(
                f' same => n,GotoIf($["${{RECORD_{member}}}"="in" | "${{RECORD_{member}}}"="all"]?rcm_page_record)'
            )
        lines.append(" same => n,Goto(rcm_page_record_continue)")
        lines.append(
            f" same => n(rcm_page_record),Set(CALLFILENAME=paging-{pid}-${{CALLERID(num)}}-${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}})"
        )
        lines.extend(recording_trigger_lines())
        lines.append(" same => n(rcm_page_record_continue),NoOp(RCM paging recording policy checked)")

        options = ""
        if duplex:
            options += "d"
        if prompt_path:
            options += f"A({prompt_path})"

        if options:
            lines.append(f" same => n,Page({targets},{options})")
        else:
            lines.append(f" same => n,Page({targets})")
        
        lines.append(" same => n,Hangup()")
        lines.append("")

    content = "\n".join(lines)
    try:
        with open("/etc/asterisk/extensions.paging.gui.conf", "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Error writing paging dialplan: {e}")
        return False
    reload_output = run_asterisk_cmd("dialplan reload")
    if reload_output == "":
        print("Paging dialplan reload returned no output")
        return False
    return True

def sync_queue_dialplan(queues):
    import db
    try:
        features = db.get_all_feature_codes()
        feat_map = {f["feature_name"]: f for f in features}
    except Exception:
        feat_map = {}

    def get_prefix(name, default_prefix):
        f = feat_map.get(name)
        if f:
            return f["feature_code"] if f["enabled"] else ""
        return default_prefix

    login_prefix = get_prefix("Queue Login", "*71")
    logout_prefix = get_prefix("Queue Logout", "*72")
    pause_prefix = get_prefix("Queue Pause", "*73")
    unpause_prefix = get_prefix("Queue Unpause", "*74")
    public_pause_prefix = get_prefix("Public Queue Pause", "*75")
    public_unpause_prefix = get_prefix("Public Queue Unpause", "*76")

    len_login = len(login_prefix)
    len_logout = len(logout_prefix)
    len_pause = len(pause_prefix)
    len_unpause = len(unpause_prefix)

    q_blocks = []
    route_lines = []
    feature_lines = ["[queue-feature-codes]"]

    def append_queue_feature_preamble(prefix, length, action_name):
        feature_lines.extend([
            f"; --- Agent {action_name} ({prefix} + Queue Number) ---",
            f"exten => _{prefix}X.,1,Answer()",
            f"same => n,Set(QNUM=${{FILTER(0-9,${{EXTEN:{length}}})}})",
            "same => n,Set(AGENT_EXT=${FILTER(0-9,${CALLERID(num)})})",
            "same => n,Set(MEMBERIFACE=PJSIP/${AGENT_EXT})"
        ])

    def append_play_queue_digits(prompt_name):
        feature_lines.extend([
            f"same => n,Playback({prompt_name})",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()"
        ])

    def append_queue_membership_scan():
        feature_lines.extend([
            "same => n,Set(QUEUE_MEMBER_FOUND=0)",
            "same => n,Set(QUEUE_MEMBER_PAUSED=0)",
            "same => n,Set(QUEUE_MEMBER_UNPAUSED=0)"
        ])
        for q in queues:
            qnum = str(q.get("queue_number", "")).strip()
            if not re.fullmatch(r"[0-9A-Za-z_.-]+", qnum):
                continue
            var_name = f"QUEUE_PAUSED_{re.sub(r'[^0-9A-Za-z_]', '_', qnum)}"
            feature_lines.extend([
                f"same => n,Set({var_name}=${{QUEUE_MEMBER({qnum},paused,${{MEMBERIFACE}})}})",
                f"same => n,ExecIf($[\"${{{var_name}}}\"=\"0\" | \"${{{var_name}}}\"=\"1\"]?Set(QUEUE_MEMBER_FOUND=1))",
                f"same => n,ExecIf($[\"${{{var_name}}}\"=\"0\"]?Set(QUEUE_MEMBER_UNPAUSED=1))",
                f"same => n,ExecIf($[\"${{{var_name}}}\"=\"1\"]?Set(QUEUE_MEMBER_PAUSED=1))"
            ])
    
    if login_prefix:
        append_queue_feature_preamble(login_prefix, len_login, "Login")
        feature_lines.extend([
            'same => n,GotoIf($["${QNUM}"=""]?invalid_queue)',
            'same => n,GotoIf($["${AGENT_EXT}"=""]?invalid_queue)',
            'same => n,GotoIf($[${QUEUE_EXISTS(${QNUM})}=0]?invalid_queue)',
            "same => n,AddQueueMember(${QNUM},${MEMBERIFACE})",
            "same => n,GotoIf($[\"${AQMSTATUS}\"=\"MEMBERALREADY\"]?already)",
            "same => n,GotoIf($[\"${AQMSTATUS}\"=\"ADDED\"]?ok_login)",
            "same => n,Goto(invalid_queue)",
            "same => n(ok_login),Playback(now_you_are_login_to_queue)",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()",
            "",
            "same => n(already),Playback(This_extension_is_already_in_this_queue)",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()",
            "same => n(invalid_queue),Playback(Sorry_this_is_an_invalid_queue)",
            "same => n,Hangup()",
            ""
        ])
        
    if logout_prefix:
        append_queue_feature_preamble(logout_prefix, len_logout, "Logout")
        feature_lines.extend([
            'same => n,GotoIf($["${QNUM}"=""]?invalid_queue)',
            'same => n,GotoIf($["${AGENT_EXT}"=""]?invalid_queue)',
            'same => n,GotoIf($[${QUEUE_EXISTS(${QNUM})}=0]?invalid_queue)',
            "same => n,RemoveQueueMember(${QNUM},${MEMBERIFACE})",
            "same => n,GotoIf($[\"${RQMSTATUS}\"=\"REMOVED\"]?ok_logout)",
            "same => n,Goto(invalid_queue)",
            "same => n(ok_logout),Playback(Now_you_are_logout_from_queue)",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()",
            "same => n(invalid_queue),Playback(Sorry_this_is_an_invalid_queue)",
            "same => n,Hangup()",
            ""
        ])

    if pause_prefix:
        append_queue_feature_preamble(pause_prefix, len_pause, "Pause")
        feature_lines.extend([
            'same => n,GotoIf($["${QNUM}"=""]?invalid_queue)',
            'same => n,GotoIf($["${AGENT_EXT}"=""]?invalid_queue)',
            'same => n,GotoIf($[${QUEUE_EXISTS(${QNUM})}=0]?invalid_queue)',
            "same => n,Set(QUEUE_PAUSED=${QUEUE_MEMBER(${QNUM},paused,${MEMBERIFACE})})",
            'same => n,GotoIf($["${QUEUE_PAUSED}"="1"]?already_paused)',
            "same => n,PauseQueueMember(${QNUM},${MEMBERIFACE},,break)",
            "same => n,GotoIf($[\"${PQMSTATUS}\"=\"PAUSED\"]?ok_pause:fail_pause)",
            "same => n(ok_pause),Playback(agent_pause_successfully_in_queue)",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()",
            "same => n(already_paused),Playback(Sorry_you_are_already_paused_in_queue)",
            "same => n,SayDigits(${QNUM})",
            "same => n,Hangup()",
            "same => n(fail_pause),Goto(invalid_queue)",
            "same => n(invalid_queue),Playback(Sorry_this_is_an_invalid_queue)",
            "same => n,Hangup()",
            ""
        ])

    if unpause_prefix:
        append_queue_feature_preamble(unpause_prefix, len_unpause, "Unpause")
        feature_lines.extend([
            'same => n,GotoIf($["${QNUM}"=""]?cant_unpause)',
            'same => n,GotoIf($["${AGENT_EXT}"=""]?cant_unpause)',
            'same => n,GotoIf($[${QUEUE_EXISTS(${QNUM})}=0]?cant_unpause)',
            "same => n,Set(QUEUE_PAUSED=${QUEUE_MEMBER(${QNUM},paused,${MEMBERIFACE})})",
            'same => n,GotoIf($["${QUEUE_PAUSED}"!="1"]?cant_unpause)',
            "same => n,UnpauseQueueMember(${QNUM},${MEMBERIFACE},,back)",
            "same => n,GotoIf($[\"${UPQMSTATUS}\"=\"UNPAUSED\"]?ok_unpause:fail_unpause)",
            "same => n(ok_unpause),Playback(agent_unpause_and_back_to_queue_successfully)",
            "same => n,Hangup()",
            "same => n(fail_unpause),Goto(cant_unpause)",
            "same => n(cant_unpause),Playback(Sorry_you_can't_unpause)",
            "same => n,Hangup()",
            ""
        ])

    if public_pause_prefix:
        feature_lines.extend([
            f"; --- Agent Public Pause ({public_pause_prefix}) ---",
            f"exten => {public_pause_prefix},1,Answer()",
            "same => n,Set(AGENT_EXT=${FILTER(0-9,${CALLERID(num)})})",
            "same => n,Set(MEMBERIFACE=PJSIP/${AGENT_EXT})",
            'same => n,GotoIf($["${AGENT_EXT}"=""]?invalid_queue)'
        ])
        append_queue_membership_scan()
        feature_lines.extend([
            'same => n,GotoIf($["${QUEUE_MEMBER_FOUND}"!="1"]?invalid_queue)',
            'same => n,GotoIf($["${QUEUE_MEMBER_UNPAUSED}"!="1"]?already_paused)',
            "same => n,PauseQueueMember(,${MEMBERIFACE},,public_pause)",
            'same => n,GotoIf($["${PQMSTATUS}"="PAUSED"]?ok_pause:invalid_queue)',
            "same => n(ok_pause),Playback(agent_pause_successfully_in_queue)",
            "same => n,Hangup()",
            "same => n(already_paused),Playback(Sorry_you_are_already_paused_in_queue)",
            "same => n,Hangup()",
            "same => n(invalid_queue),Playback(Sorry_this_is_an_invalid_queue)",
            "same => n,Hangup()",
            ""
        ])

    if public_unpause_prefix:
        feature_lines.extend([
            f"; --- Agent Public Unpause ({public_unpause_prefix}) ---",
            f"exten => {public_unpause_prefix},1,Answer()",
            "same => n,Set(AGENT_EXT=${FILTER(0-9,${CALLERID(num)})})",
            "same => n,Set(MEMBERIFACE=PJSIP/${AGENT_EXT})",
            'same => n,GotoIf($["${AGENT_EXT}"=""]?invalid_queue)'
        ])
        append_queue_membership_scan()
        feature_lines.extend([
            'same => n,GotoIf($["${QUEUE_MEMBER_FOUND}"!="1"]?invalid_queue)',
            'same => n,GotoIf($["${QUEUE_MEMBER_PAUSED}"!="1"]?cant_unpause)',
            "same => n,UnpauseQueueMember(,${MEMBERIFACE},,public_unpause)",
            'same => n,GotoIf($["${UPQMSTATUS}"="UNPAUSED"]?ok_unpause:cant_unpause)',
            "same => n(ok_unpause),Playback(agent_unpause_and_back_to_queue_successfully)",
            "same => n,Hangup()",
            "same => n(cant_unpause),Playback(Sorry_you_can't_unpause)",
            "same => n,Hangup()",
            "same => n(invalid_queue),Playback(Sorry_this_is_an_invalid_queue)",
            "same => n,Hangup()",
            ""
        ])

    feature_lines.extend([
        "[rcm-queue-features]",
        "include => queue-feature-codes",
        ""
    ])
    context_lines = []
    global_lines = []

    for q in queues:
        num = q.get("queue_number", "").strip()
        if not num:
            continue
        name = q.get("name", "").strip() or num
        strategy = q.get("strategy", "rrmemory")
        moh = q.get("music_on_hold", "default")
        max_len = q.get("max_queue_length", "0")
        wrapup = q.get("wrapup_time", "0")
        retry = q.get("retry_time", "0")
        timeout = q.get("ring_time", "0")
        auto_record = q.get("auto_record", "off")
        enable_welcome = q.get("enable_welcome_prompt", "off")
        custom_prompt = q.get("custom_prompt", "")
        welcome_mode = q.get("welcome_mode", "before")
        max_wait = q.get("max_wait_time", "0")
        dest_type = q.get("destination_type", "hangup")
        dest_val = q.get("destination_value", "")
        position_ann = q.get("position_announcement", "off")
        ann_freq = q.get("announcement_frequency", "15")
        periodic_ann = q.get("periodic_announcement", "")
        periodic_ann_freq = q.get("periodic_announcement_frequency", "30")
        caller_bridge_ann = q.get("caller_bridge_announcement", "")
        leave_empty = q.get("leave_when_empty", "yes")
        dial_empty = q.get("dial_in_empty_queue", "yes")
        report_hold = q.get("report_hold_time", "off")
        replace_cid = q.get("replace_display_name", "off")
        display_name_val = q.get("display_name_value", "") or name
        skip_busy = q.get("skip_busy_agent", "on")
        auto_fill = q.get("auto_fill", "off")
        auto_pause = q.get("auto_pause", "off")
        agent_bridge_ann = q.get("agent_bridge_announcement", "")
        members = q.get("static_agents", [])

        q_blocks.append(f"[{num}]")
        q_blocks.append(f"; RCM_NAME={name}")
        q_blocks.append(f"musicclass = {moh}")
        q_blocks.append(f"strategy = {strategy}")
        q_blocks.append(f"timeout = {timeout}")
        q_blocks.append(f"retry = {retry}")
        q_blocks.append(f"maxlen = {max_len}")
        q_blocks.append(f"wrapuptime = {wrapup}")
        q_blocks.append(f"announce-position = {position_ann}")
        q_blocks.append(f"announce-frequency = {ann_freq}")
        q_blocks.append(f"reportholdtime = {'yes' if report_hold == 'on' else 'no'}")
        q_blocks.append(f"joinempty = {dial_empty}")
        q_blocks.append(f"leavewhenempty = {leave_empty}")
        q_blocks.append(f"autofill = {'yes' if auto_fill == 'on' else 'no'}")
        q_blocks.append(f"autopause = {'yes' if auto_pause == 'on' else 'no'}")
        q_blocks.append(f"ringinuse = {'no' if skip_busy == 'on' else 'yes'}")
        q_blocks.append("setqueuevar = yes")

        # Queue recording is started on the caller channel below.  This keeps
        # the queue's recording trigger in the same one-file-per-call guard
        # as IVR, routes and extension policies.
        if periodic_ann:
            p_prompt_path = resolve_asterisk_prompt(periodic_ann)
            q_blocks.append(f"periodic-announce = {p_prompt_path}")
            q_blocks.append(f"periodic-announce-frequency = {periodic_ann_freq}")
        if caller_bridge_ann:
            c_prompt_path = resolve_asterisk_prompt(caller_bridge_ann)
            q_blocks.append(f"queue-callerannounce = {c_prompt_path}")
        if agent_bridge_ann:
            a_prompt_path = resolve_asterisk_prompt(agent_bridge_ann)
            q_blocks.append(f"announce = {a_prompt_path}")
        disabled = q.get("disabled_agents", [])
        for agent in members:
            if agent in disabled:
                q_blocks.append(f"member => PJSIP/{agent},,,,,,yes")
            else:
                q_blocks.append(f"member => PJSIP/{agent}")
        q_blocks.append("")

        global_lines.append(f"QUEUE_{num}={num}")
        route_lines.append(f"exten => {num},1,Goto(queue-{num},{num},1)")

        context_lines.append(f"[queue-{num}]")
        # Queue entry usually needs to be Answered so the caller can hear
        # Music on Hold, Welcome Prompts, and Position Announcements reliably.
        context_lines.append(f"exten => {num},1,NoOp(RCM queue entry)")
        context_lines.append(" same => n,Answer()")
        if replace_cid == "on":
            context_lines.append(f" same => n,Set(CALLERID(name)={display_name_val})")
        if enable_welcome == "on" and custom_prompt and welcome_mode == "before":
            welcome_prompt_path = resolve_asterisk_prompt(custom_prompt)
            context_lines.append(f" same => n,Playback({welcome_prompt_path},noanswer)")

        context_lines.append(
            ' same => n,GotoIf($["${RECORD_${CALLERID(num)}}"="out" | "${RECORD_${CALLERID(num)}}"="all"]?rcm_queue_record)'
        )
        for member in members:
            member = str(member).strip()
            if not re.fullmatch(r"[0-9A-Za-z_.-]+", member):
                continue
            context_lines.append(
                f' same => n,GotoIf($["${{RECORD_{member}}}"="in" | "${{RECORD_{member}}}"="all"]?rcm_queue_record)'
            )
        if auto_record == "on":
            context_lines.append(" same => n,Goto(rcm_queue_record)")
        else:
            context_lines.append(" same => n,Goto(rcm_queue_record_continue)")
        context_lines.append(
            f" same => n(rcm_queue_record),Set(CALLFILENAME=queue-{num}-${{CALLERID(num)}}-${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}})"
        )
        context_lines.extend(recording_trigger_lines())
        context_lines.append(" same => n(rcm_queue_record_continue),NoOp(RCM queue recording policy checked)")

        try:
            max_wait_int = int(max_wait)
        except (ValueError, TypeError):
            max_wait_int = 0

        if max_wait_int > 0:
            context_lines.append(f" same => n,Queue({num},tT,,,{max_wait_int})")
        else:
            context_lines.append(f" same => n,Queue({num},tT)")

        dest_action = resolve_dest_to_dialplan(dest_type, dest_val)
        context_lines.append(f" same => n,{dest_action}")
        context_lines.append("")

    q_file = "/etc/asterisk/queues.conf"
    q_text = ""
    if os.path.exists(q_file):
        with open(q_file, "r", encoding="utf-8", errors="ignore") as f:
            q_text = f.read()
    
    begin_marker = "; BEGIN RCM QUEUE GUI"
    end_marker = "; END RCM QUEUE GUI"
    new_q_block = f"{begin_marker}\n" + "\n".join(q_blocks).rstrip() + f"\n{end_marker}"
    
    pattern = re.compile(re.escape(begin_marker) + r'.*?' + re.escape(end_marker), re.S)
    if pattern.search(q_text):
        q_text = pattern.sub(new_q_block, q_text)
    else:
        if q_text and not q_text.endswith("\n"):
            q_text += "\n"
        q_text += new_q_block + "\n"
    with open(q_file, "w", encoding="utf-8") as f:
        f.write(q_text)

    lines = ["; Queue Dialplan Generated by RCM", ""]
    lines.append("[globals](+)")
    for g_line in global_lines:
        lines.append(g_line)
    lines.append("")



    lines.append("[rcm-queue-routes]")
    for r_line in route_lines:
        lines.append(r_line)
    lines.append("")

    for f_line in feature_lines:
        lines.append(f_line)
    lines.append("")

    for c_line in context_lines:
        lines.append(c_line)

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.queue.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)

    run_asterisk_cmd("dialplan reload")
    run_asterisk_cmd("queue reload all")

def sync_speed_dial_dialplan(speed_dials):
    lines = ["; Speed Dial Dialplan Generated by RCM", ""]
    lines.append("[speed-dials]")
    for sd in speed_dials:
        num = sd.get("speed_dial_num")
        dest = sd.get("destination_num")
        if num and dest:
            safe_dest = re.sub(r'[~|:;=,"\r\n]', "_", str(dest)).strip()
            lines.append(f"exten => {num},1,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~SPEED_DIAL:{num}:{safe_dest})")
            lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
            lines.append(f" same => n,Goto(from-internal-inbound,{dest},1)")
    lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.speed_dial.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
    run_asterisk_cmd("dialplan reload")

def sync_features_conf(blind_code, attended_code, abort_code):
    try:
        import db
        timeout = int(db.get_pbx_settings().get("extension_defaults", {}).get("blind_transfer_timeout", 15))
    except Exception:
        timeout = 15
    content = f"""; Features Configuration Generated by RCM
[general]
atxferabort = {abort_code}
transferdigittimeout = {timeout}

[featuremap]
blindxfer => {blind_code}
atxfer => {attended_code}
automixmon => *1

[applicationmap]
"""
    try:
        with open("/etc/asterisk/features.conf", "w", encoding="utf-8") as f:
            f.write(content)
        run_asterisk_cmd("module reload features")
    except Exception as e:
        print(f"Error writing features.conf: {e}")

def sync_feature_codes_dialplan(fc=None):
    import db
    try:
        features = db.get_all_feature_codes()
        feat_map = {f["feature_name"]: f for f in features}
    except Exception as e:
        print(f"Error fetching feature codes from DB: {e}")
        return

    def get_code_if_enabled(name, default_code=""):
        f = feat_map.get(name)
        return f["feature_code"] if (f and f["enabled"]) else ""

    # 1. Voicemail
    vm = get_code_if_enabled("My Voicemail", "*97")
    vm_access = get_code_if_enabled("Voicemail Access Code", "*98")
    
    # 2. Presence & Availability
    dnd_on = get_code_if_enabled("DND Activate", "*37")
    dnd_off = get_code_if_enabled("DND Deactivate", "*38")
    
    # 3. Call Pickup
    pickup = get_code_if_enabled("General Call Pickup", "*8")
    directed_pickup = get_code_if_enabled("Direct Call Pickup", "**")
    
    # 4. Call Transfer
    blind_t = get_code_if_enabled("Blind Transfer", "##")
    att_t = get_code_if_enabled("Attended Transfer", "*2")
    abort_t = get_code_if_enabled("Abort Transfer", "*1")
    
    # Sync transfers directly to features.conf
    sync_features_conf(blind_t, att_t, abort_t)
    
    # 5. Call Monitoring
    spy_listen = get_code_if_enabled("Listen Spy", "*54")
    spy_whisper = get_code_if_enabled("Whisper", "*55")
    spy_barge = get_code_if_enabled("Barge", "*56")
    
    # 6. Call Forwarding
    fwd_always_on = get_code_if_enabled("Forward Always Activate", "*64")
    fwd_always_off = get_code_if_enabled("Forward Always Deactivate", "*65")
    fwd_busy_on = get_code_if_enabled("Forward Busy Activate", "*58")
    fwd_busy_off = get_code_if_enabled("Forward Busy Deactivate", "*59")
    fwd_noans_on = get_code_if_enabled("Forward No Answer Activate", "*60")
    fwd_noans_off = get_code_if_enabled("Forward No Answer Deactivate", "*61")

    lines = ["; Feature Codes Dialplan Generated by RCM", ""]
    lines.append("[rcm-feature-codes]")
    
    if vm:
        lines.append(f"exten => {vm},1,Answer()")
        lines.append(f" same => n,VoiceMailMain(${{CALLERID(num)}}@default)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if vm_access:
        lines.append(f"exten => {vm_access},1,Answer()")
        lines.append(" same => n,VoiceMailMain()")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_busy_on:
        len_val = len(fwd_busy_on)
        lines.append(f"exten => _{fwd_busy_on}X.,1,Set(DB(FORWARD/BUSY/${{CALLERID(num)}})=${{EXTEN:{len_val}}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(forward_busy_to)")
        lines.append(f" same => n,SayDigits(${{EXTEN:{len_val}}})")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_busy_off:
        lines.append(f"exten => {fwd_busy_off},1,DBdeltree(FORWARD/BUSY/${{CALLERID(num)}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(rcm/media/forward_busy_deactivated)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_noans_on:
        len_val = len(fwd_noans_on)
        lines.append(f"exten => _{fwd_noans_on}X.,1,Set(DB(FORWARD/NOANSWER/${{CALLERID(num)}})=${{EXTEN:{len_val}}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(forward_no_answer_to)")
        lines.append(f" same => n,SayDigits(${{EXTEN:{len_val}}})")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_noans_off:
        lines.append(f"exten => {fwd_noans_off},1,DBdeltree(FORWARD/NOANSWER/${{CALLERID(num)}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(rcm/media/forward_no_answer_deactivated)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_always_on:
        len_val = len(fwd_always_on)
        lines.append(f"exten => _{fwd_always_on}X.,1,Set(DB(FORWARD/ALWAYS/${{CALLERID(num)}})=${{EXTEN:{len_val}}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(forward_always_to)")
        lines.append(f" same => n,SayDigits(${{EXTEN:{len_val}}})")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if fwd_always_off:
        lines.append(f"exten => {fwd_always_off},1,DBdeltree(FORWARD/ALWAYS/${{CALLERID(num)}})")
        lines.append(" same => n,Progress()")
        lines.append(" same => n,SayDigits(${CALLERID(num)})")
        lines.append(" same => n,Playback(rcm/media/forward_always_deactivated)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if dnd_on:
        lines.append(f"exten => {dnd_on},1,Set(DB(DND/${{CALLERID(num)}})=on)")
        lines.append(" same => n,Playback(do-not-disturb)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if dnd_off:
        lines.append(f"exten => {dnd_off},1,Set(DB(DND/${{CALLERID(num)}})=off)")
        lines.append(" same => n,Playback(de-activated)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if pickup:
        lines.append(f"exten => {pickup},1,Pickup()")
        lines.append(" same => n,Hangup()")
        lines.append("")

    if directed_pickup:
        len_val = len(directed_pickup)
        lines.append(f"exten => _{directed_pickup}X.,1,Pickup(${{EXTEN:{len_val}}})")
        lines.append(" same => n,Hangup()")
        lines.append("")

    def append_spy_feature(code, mode_name, chanspy_options, prompt_name):
        if not code:
            return
        len_val = len(code)
        lines.append(f"exten => _{code}X.,1,Answer()")
        lines.append(f" same => n,Set(SPY_MODE={mode_name})")
        lines.append(f" same => n,Set(TARGET=${{FILTER(0-9,${{EXTEN:{len_val}}})}})")
        lines.append(" same => n,Set(SPY_CALLER=${CHANNEL(endpoint)})")
        lines.append(' same => n,ExecIf($["${SPY_CALLER}"=""]?Set(SPY_CALLER=${CALLERID(num)}))')
        lines.append(' same => n,Set(SPY_DENY_REASON=invalid_target)')
        lines.append(' same => n,GotoIf($["${TARGET}"=""]?spy_denied)')
        lines.append(' same => n,Set(SPY_DENY_REASON=invalid_caller)')
        lines.append(' same => n,GotoIf($["${SPY_CALLER}"=""]?spy_denied)')
        lines.append(' same => n,Set(SPY_DENY_REASON=self_spy)')
        lines.append(' same => n,GotoIf($["${SPY_CALLER}"="${TARGET}"]?spy_denied)')
        lines.append(' same => n,Set(SPY_DENY_REASON=target_not_found)')
        lines.append(' same => n,GotoIf($[${DIALPLAN_EXISTS(internal,${TARGET},1)}=0]?spy_denied)')
        lines.append(" same => n,Set(TARGET_STATE=${DEVICE_STATE(PJSIP/${TARGET})})")
        lines.append(' same => n,Set(SPY_DENY_REASON=target_not_in_call)')
        lines.append(' same => n,GotoIf($["${TARGET_STATE}"!="INUSE" & "${TARGET_STATE}"!="BUSY" & "${TARGET_STATE}"!="RINGINUSE"]?spy_denied)')
        lines.append(' same => n,Set(SPY_DENY_REASON=no_permission)')
        lines.append(' same => n,GotoIf($[${DB_EXISTS(SPY/PERMIT/${TARGET}-${SPY_CALLER})}=0]?spy_denied)')
        lines.append(' same => n,Set(SPY_DENY_REASON=spy_denied)')
        lines.append(' same => n,GotoIf($["${DB(SPY/DENY/${TARGET})}"="1"]?spy_denied)')
        lines.append(f" same => n,Playback({prompt_name})")
        lines.append(" same => n,SayDigits(${TARGET})")
        lines.append(f" same => n,System(/usr/bin/python3 /root/RCM_7021/scripts/log_spy_attempt.py \"${{SPY_CALLER}}\" \"${{TARGET}}\" \"{mode_name}\" \"allowed\" \"ok\")")
        lines.append(f" same => n,ChanSpy(PJSIP/${{TARGET}},{chanspy_options})")
        lines.append(" same => n,Hangup()")
        lines.append(" same => n(spy_denied),System(/usr/bin/python3 /root/RCM_7021/scripts/log_spy_attempt.py \"${SPY_CALLER}\" \"${TARGET}\" \"${SPY_MODE}\" \"denied\" \"${SPY_DENY_REASON}\")")
        lines.append(" same => n,Playback(sorry-cant-let-you-do-that)")
        lines.append(" same => n,Hangup()")
        lines.append("")

    append_spy_feature(spy_listen, "Spy", "qE", "now_you_can_spy_to")
    append_spy_feature(spy_whisper, "Whisper", "qwE", "now_you_can_Whisper_to")
    append_spy_feature(spy_barge, "Barge", "qBE", "now_you_can_Barge_to")

    lines.append("[rcm-conferences]")
    lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.feature_codes.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
    run_asterisk_cmd("dialplan reload")

def sync_pickup_groups_dialplan(groups):
    lines = ["; Pickup Groups Dialplan Generated by RCM", ""]
    lines.append("[rcm-internal-destinations](+)")
    for pg in groups:
        num = pg.get("num") or pg.get("id")
        name = pg.get("name", "")
        members = pg.get("members", [])
        if num and members and (str(num).startswith("*") or len(str(num)) >= 3):
            targets = []
            for m in members:
                m_clean = str(m).strip()
                if m_clean:
                    targets.append(f"PJSIP/{m_clean}")
                    targets.append(f"{m_clean}@internal")
                    targets.append(f"{m_clean}@from-pstn")
                    targets.append(f"{m_clean}")
            members_str = "&".join(targets)
            lines.append(f"exten => {num},1,NoOp(Pickup Group {name})")
            lines.append(f" same => n,Pickup({members_str})")
            lines.append(" same => n,Hangup()")
            lines.append("")
    lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.pickup_groups.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
    run_asterisk_cmd("dialplan reload")

    # Sync PJSIP endpoint pickup groups from GUI numeric group ids only.
    try:
        ext_to_numeric = {}
        for pg in groups:
            gid = str(pg.get("id") or pg.get("num") or "1")
            for m in pg.get("members", []):
                m_clean = str(m).strip()
                if m_clean:
                    if m_clean not in ext_to_numeric:
                        ext_to_numeric[m_clean] = []
                    if gid.isdigit() and int(gid) <= 63 and gid not in ext_to_numeric[m_clean]:
                        ext_to_numeric[m_clean].append(gid)

        import db
        all_exts = [str(e["ext"]) for e in db.get_all_extensions()]
        for ext in all_exts:
            numeric_list = ext_to_numeric.get(ext, [])
            if numeric_list:
                num_str = ",".join(numeric_list)
                update_section(EP_FILE, ext, {
                    "call_group": num_str,
                    "pickup_group": num_str
                }, remove_keys=["named_call_group", "named_pickup_group", "named_call_pickup_group"])
            else:
                update_section(EP_FILE, ext, {}, remove_keys=["named_call_group", "named_pickup_group", "named_call_pickup_group", "call_group", "pickup_group"])
        run_asterisk_cmd("pjsip reload")
    except Exception as e:
        logger.error(f"Failed to sync PJSIP endpoint pickup groups: {e}")

def sync_announcement_dialplan(announcements):
    lines = ["; Announcements Dialplan Generated by RCM", ""]
    lines.append("[rcm-announcement-routes]")
    for ann in announcements:
        num = ann.get("num")
        if num:
            lines.append(f"exten => {num},1,Goto(ann-{num},{num},1)")
    lines.append("")

    for ann in announcements:
        num = ann.get("num")
        name = ann.get("name", "")
        prompt_id = ann.get("prompt_id")
        dest_type = ann.get("dest_type", "hangup")
        dest_val = ann.get("dest_val", "")

        if not num:
            continue

        prompt_path = resolve_asterisk_prompt(prompt_id)

        dest_line = f"same => n,{resolve_dest_to_dialplan(dest_type, dest_val)}"

        lines.append(f"; --- ANN GUI: {name} ---")
        lines.append(f"[ann-{num}]")
        lines.append(f"exten => {num},1,Answer()")
        safe_path_name = re.sub(r'[~|:;=,"\r\n]', "_", str(name or num)).strip() or str(num)
        lines.append(f" same => n,Set(__RCM_CALL_PATH=${{RCM_CALL_PATH}}~ANNOUNCEMENT:{num}:{safe_path_name})")
        lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
        lines.append(f" same => n,Playback({prompt_path})")
        lines.append(f" {dest_line}")
        lines.append("")

    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.announcement.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
    run_asterisk_cmd("dialplan reload")

# --- Music On Hold Configuration Helpers ---
def write_moh_class_config(class_name, mode):
    moh_conf_path = "/etc/asterisk/musiconhold.conf"
    dir_path = f"/var/lib/asterisk/moh/rcm/{class_name}"
    os.makedirs(dir_path, exist_ok=True)
    
    block = f"; --- RCM MOH {class_name} ---\n[{class_name}]\nmode={mode}\ndirectory={dir_path}\n\n"
    
    content = ""
    if os.path.exists(moh_conf_path):
        with open(moh_conf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
    marker = f"; --- RCM MOH {class_name} ---"
    if marker in content:
        content = re.sub(
            r';\s*---\s*RCM MOH\s+' + re.escape(class_name) + r'\s*---.*?(?=(?:;\s*---\s*RCM MOH)|\Z)',
            block,
            content,
            flags=re.DOTALL
        )
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n" + block
        
    with open(moh_conf_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    run_asterisk_cmd("moh reload")

def delete_moh_class_config(class_name):
    moh_conf_path = "/etc/asterisk/musiconhold.conf"
    if not os.path.exists(moh_conf_path):
        return
        
    with open(moh_conf_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    content = re.sub(
        r';\s*---\s*RCM MOH\s+' + re.escape(class_name) + r'\s*---.*?(?=(?:;\s*---\s*RCM MOH)|\Z)',
        "",
        content,
        flags=re.DOTALL
    )
    
    with open(moh_conf_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    dir_path = f"/var/lib/asterisk/moh/rcm/{class_name}"
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)
        
    run_asterisk_cmd("moh reload")

def apply_time_settings(settings):
    import subprocess
    mode = settings.get("mode", "automatic")
    ntp_server = settings.get("ntp_server", "pool.ntp.org")
    timezone = settings.get("timezone", "Africa/Cairo")
    ntp_server_enabled = settings.get("ntp_server_enabled", False)
    
    # 1. Apply timezone
    try:
        subprocess.run(["timedatectl", "set-timezone", timezone], check=True)
    except Exception as e:
        print(f"Error setting timezone: {e}")
        
    # 2. Apply NTP settings
    if mode == "automatic":
        try:
            # Enable systemd NTP synchronization client
            subprocess.run(["timedatectl", "set-ntp", "true"], check=True)
        except Exception as e:
            print(f"Error enabling NTP: {e}")
            
        # Write chrony.conf config
        chrony_conf = [
            "# Welcome to the chrony configuration file.",
            f"server {ntp_server} iburst",
            "keyfile /etc/chrony/chrony.keys",
            "driftfile /var/lib/chrony/chrony.drift",
            "ntsdumpdir /var/lib/chrony",
            "logdir /var/log/chrony",
            "maxupdateskew 100.0",
            "rtcsync",
            "makestep 1 3",
            "leapseclist /usr/share/zoneinfo/leap-seconds.list",
            "confdir /etc/chrony/conf.d"
        ]
        
        if ntp_server_enabled:
            chrony_conf.append("allow 0.0.0.0/0")
            
        try:
            with open("/etc/chrony/chrony.conf", "w", encoding="utf-8") as f:
                f.write("\n".join(chrony_conf) + "\n")
            # Restart chrony
            subprocess.run(["systemctl", "restart", "chrony"], check=True)
        except Exception as e:
            print(f"Error writing chrony config or restarting chrony: {e}")
            
    else:  # manual mode
        try:
            # Disable systemd NTP synchronization client
            subprocess.run(["timedatectl", "set-ntp", "false"], check=True)
        except Exception as e:
            print(f"Error disabling NTP: {e}")
            
        try:
            # Stop chrony daemon to allow manual time setting
            subprocess.run(["systemctl", "stop", "chrony"], check=True)
        except Exception as e:
            print(f"Error stopping chrony: {e}")
            
        # Set manual system time
        # Format: date_val is YYYY-MM-DD, time_val is HH:MM
        date_val = settings.get("date", "")
        time_val = settings.get("time", "")
        if date_val and time_val:
            dt_str = f"{date_val} {time_val}:00"
            try:
                subprocess.run(["timedatectl", "set-time", dt_str], check=True)
            except Exception as e:
                print(f"Error setting manual time: {e}")

def apply_network_settings(settings):
    import subprocess
    import shutil
    import stat
    mode = settings.get("mode", "dhcp")
    ip_addr = settings.get("ip_address", "")
    netmask = settings.get("subnet_mask", "")
    gateway = settings.get("gateway", "")
    dns1 = settings.get("dns1", "")
    dns2 = settings.get("dns2", "")
    
    interfaces_path = "/etc/network/interfaces"
    backup_path = "/tmp/rcm_network_interfaces.bak"
    
    if mode == "static" and (not ip_addr or not netmask or not gateway):
        raise ValueError("IP Address, Subnet Mask, and Gateway are required for Static IP.")
        
    # Backup current config. Apache runs as www-data and cannot create files
    # directly under /etc/network, so keep rollback state in /tmp.
    if os.path.exists(interfaces_path):
        shutil.copy(interfaces_path, backup_path)
        os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        
    try:
        # Generate new interfaces config
        lines = [
            "# Generated by RCM PBX GUI",
            "auto lo",
            "iface lo inet loopback",
            "",
            "allow-hotplug ens18"
        ]
        if mode == "dhcp":
            lines.append("iface ens18 inet dhcp")
        else:
            lines.append("iface ens18 inet static")
            lines.append(f"    address {ip_addr}")
            lines.append(f"    netmask {netmask}")
            lines.append(f"    gateway {gateway}")
            if dns1 or dns2:
                dns_servers = " ".join([d for d in [dns1, dns2] if d])
                lines.append(f"    dns-nameservers {dns_servers}")
                
        with open(interfaces_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            
        # Configure DNS statically if static mode. The interface file carries
        # dns-nameservers; direct resolv.conf writes are only attempted when
        # the web process has permission.
        if mode == "static":
            resolv_lines = []
            if dns1:
                resolv_lines.append(f"nameserver {dns1}")
            if dns2:
                resolv_lines.append(f"nameserver {dns2}")
            if resolv_lines and os.access("/etc/resolv.conf", os.W_OK):
                with open("/etc/resolv.conf", "w", encoding="utf-8") as f:
                    f.write("\n".join(resolv_lines) + "\n")
                    
        # Apply and rollback in the background so the HTTP request can return
        # before the network service restarts.
        script_content = """#!/bin/bash
# Asynchronously apply network settings and auto-rollback on failure
sleep 2
/usr/bin/sudo /usr/bin/systemctl restart networking
sleep 5
if ! /usr/sbin/ip addr show ens18 | /usr/bin/grep -q "inet "; then
    # No IP address assigned! Rollback to backup config
    /usr/bin/cp /tmp/rcm_network_interfaces.bak /etc/network/interfaces
    /usr/bin/sudo /usr/bin/systemctl restart networking
fi
"""
        subprocess.Popen(["/usr/bin/bash", "-c", script_content])
        return True
    except Exception as e:
        # Restore backup immediately if write fails
        if os.path.exists(backup_path):
            shutil.copy(backup_path, interfaces_path)
        raise e

def resolve_route_extensions(route):
    allowed_exts = set()
    perm_type = route.get("permission_type", "whitelist")
    
    if perm_type == "all":
        import db
        try:
            return [str(e["ext"]) for e in db.get_all_extensions() if e.get("ext")]
        except Exception:
            return []
            
    if perm_type == "whitelist":
        ext_list = route.get("allowed_extensions", [])
        if "all" in ext_list:
            import db
            try:
                return [str(e["ext"]) for e in db.get_all_extensions() if e.get("ext")]
            except Exception:
                return []
        for ext in ext_list:
            if ext:
                allowed_exts.add(str(ext))
    elif perm_type == "ring_group":
        rg_list = route.get("allowed_ring_groups", [])
        import db
        try:
            rgs = db.get_ring_groups()
        except Exception:
            rgs = []
        for rg_id in rg_list:
            for rg in rgs:
                if str(rg.get("id")) == str(rg_id):
                    for member in rg.get("members", []):
                        if member:
                            allowed_exts.add(str(member))
    return list(allowed_exts)

def rebuild_all_extensions_contexts(routes_data):
    extensions_routes = {}
    for route in routes_data:
        if not route.get("enabled", True):
            continue
        ctx = route.get("context", "")
        if not ctx:
            continue
        allowed_exts = resolve_route_extensions(route)
        for ext in allowed_exts:
            if ext not in extensions_routes:
                extensions_routes[ext] = []
            extensions_routes[ext].append(ctx)
            
    if not os.path.exists(CTX_FILE):
        content = ""
    else:
        with open(CTX_FILE, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
    import db
    try:
        all_exts = [e["ext"] for e in db.get_all_extensions()]
    except Exception:
        all_exts = []
        
    block_lines = {}
    other_lines = []
    current_block = None
    
    lines = content.splitlines()
    for line in lines:
        match = re.match(r'^\[from-internal-(\w+)\]', line.strip())
        if match:
            current_block = match.group(1)
            block_lines[current_block] = [line]
        else:
            if current_block is not None:
                line_str = line.strip()
                if line_str == "include=internal":
                    line = "include => internal"
                block_lines[current_block].append(line)
            else:
                other_lines.append(line)
                
    try:
        all_rgs = [str(r["id"]) for r in db.get_ring_groups() if r.get("id")]
    except Exception:
        all_rgs = []

    for ext in all_exts:
        allowed_routes = extensions_routes.get(ext, [])
        includes = [f"include => {r}" for r in allowed_routes]
        
        new_lines = [
            f"[from-internal-{ext}]",
            "include => internal",
            "include => rcm-ivr-routes",
            "include => rcm-queue-routes",
            "include => rcm-queue-features",
            "include => rcm-internal-destinations",
            "include => speed-dials",
            "include => code",
            "; RCM-OUT-START"
        ]
        new_lines.extend(includes)
        new_lines.append("; RCM-OUT-END")
        new_lines.append("include => rcm-no-permission")
        new_lines.append("include => inbound-route-start")
        block_lines[ext] = new_lines

    for rg_id in all_rgs:
        allowed_routes = []
        for route in routes_data:
            if not route.get("enabled", True) or not route.get("context"):
                continue
            p_type = route.get("permission_type", "whitelist")
            if p_type == "all":
                allowed_routes.append(route.get("context"))
            elif p_type == "ring_group" and str(rg_id) in [str(x) for x in route.get("allowed_ring_groups", [])]:
                allowed_routes.append(route.get("context"))
            elif p_type == "whitelist" and "all" in route.get("allowed_extensions", []):
                allowed_routes.append(route.get("context"))
        includes = [f"include => {r}" for r in allowed_routes]
        new_lines = [
            f"[from-internal-rg-{rg_id}]",
            "include => internal",
            "include => rcm-ivr-routes",
            "include => rcm-queue-routes",
            "include => rcm-queue-features",
            "include => rcm-internal-destinations",
            "include => speed-dials",
            "include => code",
            "; RCM-OUT-START"
        ]
        new_lines.extend(includes)
        new_lines.append("; RCM-OUT-END")
        new_lines.append("include => rcm-no-permission")
        new_lines.append("include => inbound-route-start")
        block_lines[f"rg-{rg_id}"] = new_lines

    new_content_parts = []
    if other_lines:
        new_content_parts.append("\n".join(other_lines))
        
    for ext in sorted(block_lines.keys()):
        if ext in all_exts or ext.startswith("rg-"):
            new_content_parts.append("\n".join(block_lines[ext]))
            
    final_content = "\n\n".join(new_content_parts) + "\n"
    with open(CTX_FILE, "w", encoding="utf-8") as f:
        f.write(final_content)

def sync_outbound_routes(routes):
    routes = [
        route for _, route in sorted(
            enumerate(routes or []),
            key=lambda item: (
                _safe_int(item[1].get("priority"), item[0] + 1),
                str(item[1].get("name") or "").lower()
            )
        )
    ]
    rebuild_all_extensions_contexts(routes)

    try:
        write_outbound_routes_dialplan(routes)
    except Exception as e:
        print(f"Error generating outbound routes dialplan in Python: {e}")
        
    run_asterisk_cmd("dialplan reload")

def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")

def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _sanitize_dialplan_name(value):
    return re.sub(r'[^A-Za-z0-9_]', '_', str(value or "").strip()) or "default"

def _build_dod_lookup_context(context_name, trunk_name, route_name, trunk_dods, route_dods):
    lines = [
        f"[{context_name}]",
        f"exten => s,1,NoOp(Outbound DOD lookup route={route_name} trunk={trunk_name} caller=${{CALLERID(num)}})",
    ]

    def add_dod_group(group_label, dod_records):
        for dod in dod_records or []:
            dod_number = str(dod.get("dod_number") or "").strip()
            if not dod_number:
                continue
            for ext in dod.get("extensions", []) or []:
                ext = str(ext or "").strip()
                if not ext:
                    continue
                lines.append(f' same => n,GotoIf($["${{RCM_CALLER_EXT}}"="{ext}"]?{group_label}_{dod["id"]}_{ext})')
        for dod in dod_records or []:
            dod_number = str(dod.get("dod_number") or "").strip()
            if not dod_number:
                continue
            for ext in dod.get("extensions", []) or []:
                ext = str(ext or "").strip()
                if not ext:
                    continue
                lines.append(f" same => n({group_label}_{dod['id']}_{ext}),Set(CALLERID(num)={dod_number})")
                lines.append(" same => n,Return()")
    
    add_dod_group("trunkdod", trunk_dods)
    add_dod_group("routedod", route_dods)
    lines.append(" same => n,Return()")
    lines.append("")
    return lines

def write_outbound_routes_dialplan(routes, out_conf="/etc/asterisk/rcm_outbound_routes.conf"):
    enabled_trunks = None
    trunk_dod_cache = {}
    route_dod_cache = {}
    try:
        import db
        all_trunks = db.get_all_trunks()
        if os.path.abspath(out_conf) == os.path.abspath("/etc/asterisk/rcm_outbound_routes.conf"):
            enabled_trunks = {
                str(t.get("name")).strip()
                for t in all_trunks
                if str(t.get("name") or "").strip() and _truthy(t.get("enabled", True))
            }
        trunk_dod_cache = {str(t.get("name")).strip(): db.get_trunk_dods(str(t.get("name")).strip()) for t in all_trunks if str(t.get("name") or "").strip()}
        route_dod_cache = {str(route.get("name") or "").strip(): db.get_outbound_route_dods(str(route.get("name") or "").strip()) for route in routes or [] if str(route.get("name") or "").strip()}
    except Exception as e:
        print(f"Error loading enabled trunks for outbound routes: {e}")

    lines = [
        "; =====================================================",
        "; RCM Outbound Routes - AUTOGENERATED",
        "; Source: RCM Python generator",
        "; =====================================================",
        "",
    ]

    for route in routes or []:
        if not _truthy(route.get("enabled", True)):
            continue

        ctx = (route.get("context") or f"rcm-out-{route.get('name', '')}").strip()
        if not ctx:
            continue

        raw_patterns = [p.strip() for p in route.get("patterns", []) if str(p).strip()]
        if not raw_patterns:
            match_pattern = str(route.get("match_pattern", "")).strip()
            if match_pattern:
                pattern = f"{route.get('prefix', '')}{match_pattern.lstrip('_')}"
                raw_patterns = [pattern]
        patterns = []
        for pat in raw_patterns:
            if any(c in pat for c in ["X", "Z", "N", ".", "!", "[", "]"]) and not pat.startswith("_"):
                pat = "_" + pat
            patterns.append(pat)
        if not patterns:
            continue

        trunks = [str(t).strip() for t in route.get("trunks", []) if str(t).strip()]
        if enabled_trunks is not None:
            trunks = [trunk for trunk in trunks if trunk in enabled_trunks]
        if not trunks:
            continue

        route_name = str(route.get("name", ctx)).strip()
        route_dods = route_dod_cache.get(route_name, [])

        timeout = max(_safe_int(route.get("timeout"), 30), 1)
        strip = max(_safe_int(route.get("strip"), 0), 0)
        prepend = str(route.get("prepend") or "")
        pin = str(route.get("pin") or "").strip()
        record = _truthy(route.get("record", False))
        time_limit_sec = max(_safe_int(route.get("time_limit_sec"), 0), 0)
        dial_opts = "Tt"
        if time_limit_sec:
            dial_opts += f"L({time_limit_sec * 1000})"

        lines.append(f"[{ctx}]")
        for pattern in patterns:
            route_name = route.get("name", ctx)
            lines.append(f"exten => {pattern},1,NoOp(RCM-OUT route={ctx} name={route_name} caller=${{CALLERID(num)}} ext=${{EXTEN}})")
            lines.append(" same => n,Set(RCM_DIAL=${EXTEN})")
            if strip:
                lines.append(f" same => n,Set(RCM_DIAL=${{RCM_DIAL:{strip}}})")
            if prepend:
                lines.append(f" same => n,Set(RCM_DIAL={prepend}${{RCM_DIAL}})")
            if pin:
                lines.append(f" same => n,Authenticate({pin})")
            if record:
                lines.append(" same => n,Set(CALLFILENAME=out-${EXTEN}-${CALLERID(num)}-${STRFTIME(${EPOCH},,%Y%m%d-%H%M%S)})")
            lines.append(f" same => n,Set(RCM_ROUTE_RECORD={'1' if record else '0'})")
            lines.append(
                ' same => n,GotoIf($["${RCM_ROUTE_RECORD}"="1" | "${RECORD_${CALLERID(num)}}"="out" | "${RECORD_${CALLERID(num)}}"="all"]?rcm_out_record:rcm_out_record_continue)'
            )
            lines.extend([" same => n(rcm_out_record),Gosub(rcm-recording,start,1)", " same => n(rcm_out_record_continue),NoOp(RCM outbound recording policy checked)"])
            lines.append(" same => n,Set(__RCM_CALLER_EXT=${FILTER(0-9,${CALLERID(num)})})")
            for trunk in trunks:
                trunk_dods = trunk_dod_cache.get(str(trunk).strip(), [])
                if trunk_dods or route_dods:
                    dod_ctx = f"rcm-out-dod-{_sanitize_dialplan_name(route_name)}-{_sanitize_dialplan_name(trunk)}"
                    lines.append(f" same => n,Gosub({dod_ctx},s,1)")
                lines.append(f" same => n,Dial(PJSIP/${{RCM_DIAL}}@{trunk},{timeout},{dial_opts})")
                lines.append(' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)')
            lines.append(' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy_fail)')
            lines.append(" same => n,Playtones(congestion)")
            lines.append(" same => n,Busy(3)")
            lines.append(" same => n,Hangup()")
            lines.append(" same => n(busy_fail),Playtones(busy)")
            lines.append(" same => n,Busy(5)")
            lines.append(" same => n(done),Hangup()")
            lines.append("")
        lines.append("")

        for trunk in trunks:
            trunk_dods = trunk_dod_cache.get(str(trunk).strip(), [])
            if not trunk_dods and not route_dods:
                continue
            dod_ctx = f"rcm-out-dod-{_sanitize_dialplan_name(route_name)}-{_sanitize_dialplan_name(trunk)}"
            lines.extend(_build_dod_lookup_context(dod_ctx, trunk, route_name, trunk_dods, route_dods))

    with open(out_conf, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def date_to_epoch(date_str, end_of_day=False):
    import time
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            else:
                dt = dt.replace(hour=0, minute=0, second=0)
            return int(time.mktime(dt.timetuple()))
        except ValueError:
            continue
    return 0

def date_to_mmdd(date_str):
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%m%d")
        except ValueError:
            continue
    return "0101"

def ensure_inbound_include():
    context_file = "/etc/asterisk/extensions.context.conf"
    include_line = "#include extensions.inbound.gui.conf"
    if os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if include_line not in content:
            with open(context_file, "a", encoding="utf-8") as f:
                f.write("\n" + include_line + "\n")

def _inbound_entry_context_block(context_name):
    return "\n".join([
        f"[{context_name}]",
        f"exten => _X.,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,s,1)",
        f"exten => _+X.,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,s,1)",
        f"exten => _*X.,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,s,1)",
        f"exten => s,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,s,1)",
        f"exten => i,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,i,1)",
        f"exten => t,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,t,1)",
        f"exten => h,1,Set(__RCM_INBOUND_DID=${{EXTEN}})",
        f" same => n,Set(__RCM_INBOUND_TRUNK=${{CHANNEL(endpoint)}})",
        f" same => n,Set(__RCM_INBOUND_CTX={context_name})",
        " same => n,Goto(inbound-route-start,h,1)",
    ])

def ensure_inbound_entry_contexts(context_names):
    extensions_file = "/etc/asterisk/extensions.conf"
    if not os.path.exists(extensions_file):
        return

    safe_contexts = []
    for context_name in context_names:
        context_name = str(context_name or "").strip()
        if context_name and context_name != "from-trunk" and re.match(r"^[A-Za-z0-9_.-]+$", context_name):
            safe_contexts.append(context_name)
    if not safe_contexts:
        return

    with open(extensions_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    for context_name in sorted(set(safe_contexts)):
        block = _inbound_entry_context_block(context_name)
        pattern = re.compile(
            rf"(?ms)^\[{re.escape(context_name)}\]\n.*?(?=^\[[^\]]+\]|\Z)"
        )
        if pattern.search(content):
            content = pattern.sub(block + "\n\n", content)
        else:
            content = content.rstrip() + "\n\n" + block + "\n"

    with open(extensions_file, "w", encoding="utf-8") as f:
        f.write(content)

def get_inbound_entry_contexts(inbound_routes, trunks):
    contexts = {"from-trunk"}
    enabled_trunks = {
        str(t.get("name")): str(t.get("context") or "from-trunk")
        for t in trunks
        if t.get("name") and bool(t.get("enabled", 1))
    }
    trunk_contexts = {
        str(t.get("name")): str(t.get("context") or "from-trunk")
        for t in trunks
        if t.get("name")
    }

    for route in inbound_routes:
        if not bool(route.get("enabled", True)):
            continue
        selected_trunks = [str(t).strip() for t in route.get("trunks", []) if str(t).strip()]
        selected_enabled = [t for t in selected_trunks if t in enabled_trunks]
        if selected_enabled:
            for trunk_name in selected_enabled:
                contexts.add(enabled_trunks.get(str(trunk_name), "from-trunk"))
        elif not selected_trunks:
            contexts.update(enabled_trunks.values())
        else:
            continue
    return contexts

def get_trunk_match_values(selected_trunks, trunks):
    trunk_rows = {str(t.get("name")): t for t in trunks if t.get("name") and bool(t.get("enabled", 1))}
    endpoint_values = set()
    context_values = set()
    selected_trunks = [str(t or "").strip() for t in selected_trunks or [] if str(t or "").strip()]
    selected_enabled = [t for t in selected_trunks if t in trunk_rows]

    if selected_trunks and not selected_enabled:
        return ["__NO_ENABLED_TRUNK__"], []

    for trunk_name in selected_enabled:
        endpoint_values.add(trunk_name)
        row = trunk_rows.get(trunk_name, {})
        for key in ("username", "auth_id", "from_user"):
            value = str(row.get(key) or "").strip()
            if value:
                endpoint_values.add(value)
        context = str(row.get("context") or "").strip()
        if context:
            context_values.add(context)

    return sorted(endpoint_values), sorted(context_values)

def trunk_skip_condition(selected_trunks, trunks):
    if not selected_trunks or any(str(t).lower() in ("any", "all", "*") for t in selected_trunks):
        return ""
    endpoint_values, context_values = get_trunk_match_values(selected_trunks, trunks)
    checks = [f'"${{TRUNK}}" != "{value}"' for value in endpoint_values]
    checks.extend([f'"${{TRUNK_CTX}}" != "{value}"' for value in context_values])
    if not checks:
        return ""
    return " && ".join(checks)

def combine_route_pattern(did_pattern, cid_pattern):
    did_pattern = (did_pattern or "_X.").strip()
    cid_pattern = (cid_pattern or "").strip()
    did_body = did_pattern[1:] if did_pattern.startswith("_") else did_pattern
    cid_body = cid_pattern[1:] if cid_pattern.startswith("_") else cid_pattern
    prefix = "_" if did_pattern.startswith("_") or cid_pattern.startswith("_") else ""
    return f"{prefix}{did_body}-{cid_body}"

def _normalize_inbound_did_pattern(pattern):
    pattern = str(pattern or "").strip()
    if not pattern:
        return ""
    if pattern in {"s", "i", "t", "h"}:
        return pattern
    if pattern.startswith("_"):
        body = pattern[1:]
        body = body.replace("x", "X").replace("n", "N").replace("z", "Z")
        return f"_{body}"
    if pattern.isdigit():
        return pattern
    if re.search(r"[xXnNzZ\.\[\]\-\*]", pattern):
        body = pattern.replace("x", "X").replace("n", "N").replace("z", "Z")
        return f"_{body}"
    return pattern

def sync_inbound_routes_dialplan():
    ensure_inbound_include()
    import db
    
    office_times = db.get_office_times()
    holidays = db.get_holidays()
    inbound_routes = db.get_inbound_routes()
    trunks_db = db.get_all_trunks()

    def append_unmatched_returns(target_lines, existing_extens=None):
        existing = {str(ext or "").strip() for ext in (existing_extens or []) if str(ext or "").strip()}
        for fallback_exten in ["_X.", "_+X.", "_*X.", "_[0-9a-zA-Z].", "s", "i", "t", "h"]:
            if fallback_exten not in existing:
                target_lines.append(f"exten => {fallback_exten},1,Return()")
    
    ensure_inbound_entry_contexts(get_inbound_entry_contexts(inbound_routes, trunks_db))
    
    lines = [
        "; =====================================================",
        "; RCM Inbound Routes Dialplan - AUTOGENERATED",
        "; =====================================================",
        ""
    ]
    
    # 1. Generate check subroutines for Office Times
    lines.append("; --- Office Time Subroutines ---")
    for ot in office_times:
        ot_id = ot.get("id")
        ot_name = ot.get("name", "")
        
        lines.append(f"[rcm-check-office-{ot_id}]")
        
        # Check if enabled
        is_enabled = ot.get("enabled", 1)
        if not is_enabled:
            lines.append("exten => s,1,Return(0)")
            lines.append("")
            continue
            
        exten_idx = 1
        rules = ot.get("rules", [])
        if rules:
            for r in rules:
                day = r.get("day_of_week", "")
                start = r.get("start_time", "")
                end = r.get("end_time", "")
                if day and start and end:
                    time_range = f"{start}-{end}"
                    day_abbr = day[:3].lower()
                    if exten_idx == 1:
                        lines.append(f"exten => s,{exten_idx},GotoIfTime({time_range},{day_abbr},*,*?matched)")
                    else:
                        lines.append(f" same => n,GotoIfTime({time_range},{day_abbr},*,*?matched)")
                    exten_idx += 1
                    
        if exten_idx == 1:
            lines.append("exten => s,1,Return(0)")
        else:
            lines.append(" same => n,Return(0)")
            lines.append(" same => n(matched),Return(1)")
        lines.append("")
        
    # 2. Generate check subroutines for Holidays
    lines.append("; --- Holiday Subroutines ---")
    for h in holidays:
        h_id = h.get("id")
        h_name = h.get("name", "")
        start_date = h.get("start_date", "")
        end_date = h.get("end_date", "")
        recurring = bool(h.get("recurring", False))
        
        lines.append(f"[rcm-check-holiday-{h_id}]")
        
        if not start_date or not end_date:
            lines.append("exten => s,1,Return(0)")
            lines.append("")
            continue
            
        if recurring:
            start_mmdd = date_to_mmdd(start_date)
            end_mmdd = date_to_mmdd(end_date)
            lines.append("exten => s,1,Set(curr_md=${STRFTIME(${EPOCH},,%m%d)})")
            if int(start_mmdd) <= int(end_mmdd):
                lines.append(f" same => n,GotoIf($[ ${{curr_md}} >= {start_mmdd} && ${{curr_md}} <= {end_mmdd} ]?matched)")
            else:
                lines.append(f" same => n,GotoIf($[ ${{curr_md}} >= {start_mmdd} || ${{curr_md}} <= {end_mmdd} ]?matched)")
            lines.append(" same => n,Return(0)")
            lines.append(" same => n(matched),Return(1)")
        else:
            start_epoch = date_to_epoch(start_date, False)
            end_epoch = date_to_epoch(end_date, True)
            lines.append(f"exten => s,1,GotoIf($[ ${{EPOCH}} >= {start_epoch} && ${{EPOCH}} <= {end_epoch} ]?matched)")
            lines.append(" same => n,Return(0)")
            lines.append(" same => n(matched),Return(1)")
        lines.append("")
        
    # 3. Generate from-trunk context
    lines.append("; --- Main Entry Point ---")
    lines.append("[from-trunk]")
    lines.append("exten => _X.,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,s,1)")
    lines.append("exten => _+X.,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,s,1)")
    lines.append("exten => _*X.,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,s,1)")
    lines.append("exten => s,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,s,1)")
    lines.append("exten => i,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,i,1)")
    lines.append("exten => t,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,t,1)")
    lines.append("exten => h,1,Set(__RCM_INBOUND_DID=${EXTEN})")
    lines.append(" same => n,Set(__RCM_INBOUND_TRUNK=${CHANNEL(endpoint)})")
    lines.append(" same => n,Goto(inbound-route-start,h,1)")
    lines.append("")

    lines.append("[inbound-route-start]")
    for pattern in ["_X.", "_+X.", "_*X.", "_[0-9a-zA-Z]."]:
        lines.append(f"exten => {pattern},1,ExecIf($[ \"${{RCM_INBOUND_DID}}\" = \"\" ]?Set(__RCM_INBOUND_DID=${{EXTEN}}))")
        lines.append(" same => n,Goto(inbound-route-eval,s,1)")
    for special_ext in ["s", "i", "t", "h"]:
        lines.append(f"exten => {special_ext},1,ExecIf($[ \"${{RCM_INBOUND_DID}}\" = \"\" ]?Set(__RCM_INBOUND_DID=${{EXTEN}}))")
        lines.append(" same => n,Goto(inbound-route-eval,s,1)")
            
    lines.append("")
    lines.append("[inbound-route-eval]")
    lines.append("exten => s,1,NoOp(Inbound call evaluation started)")
    lines.append(" same => n,Set(DID=${RCM_INBOUND_DID})")
    lines.append(' same => n,ExecIf($[ "${DID}" = "" ]?Set(DID=${EXTEN}))')
    lines.append(" same => n,Set(CID=${CALLERID(num)})")
    lines.append(" same => n,Set(CID_NORM=${FILTER(0-9,${CID})})")
    lines.append(' same => n,GotoIf($[ "${CID_NORM:0:3}" = "002" ]?cid_strip_002)')
    lines.append(' same => n,GotoIf($[ "${CID_NORM:0:2}" = "20" ]?cid_strip_2)')
    lines.append(" same => n,Goto(cid_norm_done)")
    lines.append(" same => n(cid_strip_002),Set(CID_NORM=${CID_NORM:3})")
    lines.append(' same => n,GotoIf($[ "${CID_NORM:0:2}" = "20" ]?cid_strip_2)')
    lines.append(" same => n,Goto(cid_norm_done)")
    lines.append(" same => n(cid_strip_2),Set(CID_NORM=${CID_NORM:1})")
    lines.append(" same => n(cid_norm_done),NoOp(Normalized CID=${CID_NORM})")
    lines.append(" same => n,Set(TRUNK=${RCM_INBOUND_TRUNK})")
    lines.append(" same => n,ExecIf($[ \"${TRUNK}\" = \"\" ]?Set(TRUNK=${CHANNEL(endpoint)}))")
    lines.append(" same => n,Set(__RCM_CALL_PATH=${RCM_CALL_PATH}~INBOUND:${TRUNK}:${DID})")
    lines.append(" same => n,Set(CDR(userfield)=${RCM_CALL_PATH})")
    lines.append(" same => n,Set(TRUNK_CTX=${RCM_INBOUND_CTX})")
    lines.append(" same => n,ExecIf($[ \"${TRUNK_CTX}\" = \"\" ]?Set(TRUNK_CTX=${CHANNEL(context)}))")
    
    for idx, route in enumerate(inbound_routes):
        r_id = route.get("id")
        r_name = route.get("name", f"Route {idx+1}")
        enabled = bool(route.get("enabled", True))
        if not enabled:
            continue
            
        trunks = route.get("trunks", [])
        did_patterns = route.get("did_patterns", [])
        cid_pattern = route.get("cid_pattern", "").strip()
        
        lines.append(f"; Evaluate: {r_name}")
        lines.append(f" same => n,Set(ROUTE_MATCHED=0)")
        
        # Trunk filter
        if trunks:
            trunk_skip = trunk_skip_condition(trunks, trunks_db)
            if trunk_skip:
                lines.append(f' same => n,GotoIf($[ {trunk_skip} ]?skip_r_{r_id})')
            
        # DID/CID filter
        if did_patterns or cid_pattern:
            lines.append(f" same => n,Gosub(rcm-check-route-{r_id},check,1)")
            lines.append(f' same => n,GotoIf($[ "${{ROUTE_MATCHED}}" = "1" ]?rcm-route-{r_id}-matched,s,1)')
        else:
            lines.append(f" same => n,Goto(rcm-route-{r_id}-matched,s,1)")
            
        lines.append(f" same => n(skip_r_{r_id}),NoOp(Skipped route {r_name})")

    fallback_routes = [r for r in inbound_routes if bool(r.get("enabled", True)) and r.get("cid_pattern", "").strip()]
    if fallback_routes:
        lines.append("; CID fallback: keep DID routes reachable when caller ID format is unexpected")
        for route in fallback_routes:
            r_id = route.get("id")
            r_name = route.get("name", r_id)
            selected_trunks = route.get("trunks", [])
            lines.append(f" same => n,Set(ROUTE_MATCHED=0)")
            if selected_trunks:
                trunk_skip = trunk_skip_condition(selected_trunks, trunks_db)
                if trunk_skip:
                    lines.append(f' same => n,GotoIf($[ {trunk_skip} ]?skip_r_{r_id}_cidfb)')
            lines.append(f" same => n,Gosub(rcm-check-route-{r_id}-didonly,check,1)")
            lines.append(f' same => n,GotoIf($[ "${{ROUTE_MATCHED}}" = "1" ]?rcm-route-{r_id}-matched,s,1)')
            lines.append(f" same => n(skip_r_{r_id}_cidfb),NoOp(Skipped CID fallback route {r_name})")
        
    lines.append(" same => n,NoOp(No inbound route matched)")
    lines.append(' same => n,GotoIf($[ ${REGEX("^[0-9]+$" ${DID})} && ${DIALPLAN_EXISTS(internal,${DID},1)} ]?internal,${DID},1)')
    lines.append(" same => n,Playback(ss-noservice)")
    lines.append(" same => n,Hangup()")
    lines.append("")
    
    # 5. Generate matching helper contexts for each route
    for route in inbound_routes:
        r_id = route.get("id")
        enabled = bool(route.get("enabled", True))
        if not enabled:
            continue
            
        did_patterns = route.get("did_patterns", [])
        cid_pattern = route.get("cid_pattern", "").strip()

        if did_patterns and cid_pattern:
            lines.append(f"[rcm-check-route-{r_id}]")
            lines.append(f"exten => check,1,Goto(rcm-check-route-{r_id}-did,${{DID}},1)")
            lines.append("")
            lines.append(f"[rcm-check-route-{r_id}-did]")
            did_extens = []
            for d in did_patterns:
                clean_d = _normalize_inbound_did_pattern(d)
                did_extens.append(clean_d)
                lines.append(f"exten => {clean_d},1,Goto(rcm-check-route-{r_id}-cid,${{CID_NORM}},1)")
            append_unmatched_returns(lines, did_extens)
            lines.append("")
            lines.append(f"[rcm-check-route-{r_id}-cid]")
            clean_cid_pattern = _normalize_inbound_did_pattern(cid_pattern)
            lines.append(f"exten => {clean_cid_pattern},1,Set(ROUTE_MATCHED=1)")
            lines.append(" same => n,Return()")
            append_unmatched_returns(lines, [clean_cid_pattern])
            lines.append("")
        elif did_patterns:
            lines.append(f"[rcm-check-route-{r_id}]")
            lines.append(f"exten => check,1,Goto(rcm-check-route-{r_id}-did,${{DID}},1)")
            lines.append("")
            lines.append(f"[rcm-check-route-{r_id}-did]")
            did_extens = []
            for d in did_patterns:
                clean_d = _normalize_inbound_did_pattern(d)
                did_extens.append(clean_d)
                lines.append(f"exten => {clean_d},1,Set(ROUTE_MATCHED=1)")
                lines.append(" same => n,Return()")
            append_unmatched_returns(lines, did_extens)
            lines.append("")
        elif cid_pattern:
            lines.append(f"[rcm-check-route-{r_id}]")
            lines.append(f"exten => check,1,Goto(rcm-check-route-{r_id}-cid,${{CID_NORM}},1)")
            lines.append("")
            lines.append(f"[rcm-check-route-{r_id}-cid]")
            clean_cid_pattern = _normalize_inbound_did_pattern(cid_pattern)
            lines.append(f"exten => {clean_cid_pattern},1,Set(ROUTE_MATCHED=1)")
            lines.append(" same => n,Return()")
            append_unmatched_returns(lines, [clean_cid_pattern])
            lines.append("")

        if did_patterns and cid_pattern:
            lines.append(f"[rcm-check-route-{r_id}-didonly]")
            lines.append(f"exten => check,1,Goto(rcm-check-route-{r_id}-didonly-match,${{DID}},1)")
            lines.append("")
            lines.append(f"[rcm-check-route-{r_id}-didonly-match]")
            did_extens = []
            for d in did_patterns:
                clean_d = _normalize_inbound_did_pattern(d)
                did_extens.append(clean_d)
                lines.append(f"exten => {clean_d},1,Set(ROUTE_MATCHED=1)")
                lines.append(" same => n,Return()")
            append_unmatched_returns(lines, did_extens)
            lines.append("")
            
    # 6. Generate action contexts for each matched route
    for route in inbound_routes:
        r_id = route.get("id")
        r_name = route.get("name")
        enabled = bool(route.get("enabled", True))
        if not enabled:
            continue
            
        auto_record = bool(route.get("auto_record", False))
        enable_dial_trunk = bool(route.get("enable_dial_trunk", False))
        dial_trunk_permission_ext = str(route.get("dial_trunk_permission_ext", "") or "").strip()
        rules = route.get("rules", [])
        
        default_dest_type = route.get("default_dest_type", "hangup")
        default_dest_val = route.get("default_dest_val", "")
        default_strip = route.get("default_strip", 0)
        default_prepend = route.get("default_prepend", "")
        
        lines.append(f"[rcm-route-{r_id}-matched]")
        exten_idx = 1
        
        lines.append(f"exten => s,{exten_idx},NoOp(Inbound Route: {r_name} Matched)")
        exten_idx += 1
        
        if auto_record:
            lines.append(f" same => n,Set(CALLFILENAME=in-{r_id}-${{DID}}-${{CALLERID(num)}}-${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}})")
            lines.extend(recording_trigger_lines())
            
        if enable_dial_trunk and dial_trunk_permission_ext and re.match(r"^[A-Za-z0-9_]+$", dial_trunk_permission_ext):
            lines.append(f" same => n,Set(__RCM_ENABLE_DIAL_TRUNK=1)")
            lines.append(f" same => n,Set(__RCM_DIAL_THROUGH_PERMISSION_EXT={dial_trunk_permission_ext})")
            lines.append(f" same => n,NoOp(Dial Through Trunk using extension permission {dial_trunk_permission_ext} for DID ${{DID}})")
            lines.append(f" same => n,Goto(from-internal-{dial_trunk_permission_ext},${{DID}},1)")
            lines.append("")
            continue
            
        for r_idx, rule in enumerate(rules):
            tc = rule.get("time_condition", "always")
            office_prof = rule.get("office_profile", "")
            holiday_prof = rule.get("holiday_profile", "")
            custom_days = rule.get("custom_days", [])
            custom_start = rule.get("custom_start", "")
            custom_end = rule.get("custom_end", "")
            
            dest_type = rule.get("dest_type", "hangup")
            dest_val = rule.get("dest_val", "")
            strip_count = rule.get("strip", 0)
            prepend_val = rule.get("prepend", "")
            
            final_dest = apply_strip_prepend(dest_val, strip_count, prepend_val)
            dest_action = resolve_dest_to_dialplan(dest_type, final_dest)
            
            label = f"rule_{r_idx}_dest"
            
            if tc == "office" and office_prof:
                lines.append(f" same => n,Gosub(rcm-check-office-{office_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{GOSUB_RETVAL}}" = "1" ]?{label})')
            elif tc == "out_office" and office_prof:
                lines.append(f" same => n,Gosub(rcm-check-office-{office_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{GOSUB_RETVAL}}" = "0" ]?{label})')
            elif tc == "holiday" and holiday_prof:
                lines.append(f" same => n,Gosub(rcm-check-holiday-{holiday_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{GOSUB_RETVAL}}" = "1" ]?{label})')
            elif tc == "out_holiday" and holiday_prof:
                lines.append(f" same => n,Gosub(rcm-check-holiday-{holiday_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{GOSUB_RETVAL}}" = "0" ]?{label})')
            elif tc == "out_office_holiday" and office_prof and holiday_prof:
                lines.append(f" same => n,Gosub(rcm-check-office-{office_prof},s,1)")
                lines.append(f" same => n,Set(OFF_M=${{GOSUB_RETVAL}})")
                lines.append(f" same => n,Gosub(rcm-check-holiday-{holiday_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{OFF_M}}" = "0" | "${{GOSUB_RETVAL}}" = "1" ]?{label})')
            elif tc == "office_out_holiday" and office_prof and holiday_prof:
                lines.append(f" same => n,Gosub(rcm-check-office-{office_prof},s,1)")
                lines.append(f" same => n,Set(OFF_M=${{GOSUB_RETVAL}})")
                lines.append(f" same => n,Gosub(rcm-check-holiday-{holiday_prof},s,1)")
                lines.append(f' same => n,GotoIf($[ "${{OFF_M}}" = "1" & "${{GOSUB_RETVAL}}" = "0" ]?{label})')
            elif tc == "custom" and custom_days and custom_start and custom_end:
                time_range = f"{custom_start}-{custom_end}"
                for c_day in custom_days:
                    c_day_abbr = c_day[:3].lower()
                    lines.append(f" same => n,GotoIfTime({time_range},{c_day_abbr},*,*?{label})")
                    
        final_default_dest = apply_strip_prepend(default_dest_val, default_strip, default_prepend)
        default_action = resolve_dest_to_dialplan(default_dest_type, final_default_dest)
        lines.append(f" same => n,{default_action}")
        
        for r_idx, rule in enumerate(rules):
            dest_type = rule.get("dest_type", "hangup")
            dest_val = rule.get("dest_val", "")
            strip_count = rule.get("strip", 0)
            prepend_val = rule.get("prepend", "")
            
            final_dest = apply_strip_prepend(dest_val, strip_count, prepend_val)
            dest_action = resolve_dest_to_dialplan(dest_type, final_dest)
            
            label = f"rule_{r_idx}_dest"
            lines.append(f" same => n({label}),{dest_action}")
            
        lines.append("")
        
    # 7. Generate rcm-inbound-dial-trunk context containing outbound routes
    lines.append("; --- Outbound Rules Wrapper ---")
    lines.append("[rcm-inbound-dial-trunk]")
    outbound_routes = db.get_outbound_routes()
    for route in outbound_routes:
        if route.get("enabled", True):
            ctx = route.get("context") or f"rcm-out-{route.get('name')}"
            lines.append(f"include => {ctx}")
    lines.append("")
    
    # 8. Append from-internal-inbound wrapper context to handle Enable Dial Trunk transit calls
    lines.append("; --- Authorized Inbound Transit Context ---")
    lines.append("[from-internal-inbound]")
    lines.append("include => internal")
    lines.append("include => rcm-inbound-dial-trunk")
    lines.append("")
    
    content = "\n".join(lines)
    with open("/etc/asterisk/extensions.inbound.gui.conf", "w", encoding="utf-8") as f:
        f.write(content)
        
    run_asterisk_cmd("dialplan reload")

def apply_strip_prepend(value, strip_count, prepend_val):
    if not value:
        return ""
    value_str = str(value).strip()
    perm_suffix = ""
    if "|" in value_str:
        parts = value_str.split("|", 1)
        value_str = parts[0]
        perm_suffix = "|" + parts[1]
    try:
        strip_count = int(strip_count)
    except (ValueError, TypeError):
        strip_count = 0
    if strip_count > 0:
        value_str = value_str[strip_count:]
    if prepend_val:
        value_str = str(prepend_val) + value_str
    return value_str + perm_suffix

# --- AMI Call Center Interface ---
import socket

def send_ami_command(action, parameters=None):
    if parameters is None:
        parameters = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", 5038))
        
        # Read greeting
        greeting = s.recv(1024).decode('utf-8', errors='ignore')
        
        # Login
        login_cmd = "Action: Login\r\nUsername: guiuser\r\nSecret: admin\r\n\r\n"
        s.sendall(login_cmd.encode('utf-8'))
        
        login_res = ""
        while "\r\n\r\n" not in login_res:
            chunk = s.recv(1024).decode('utf-8', errors='ignore')
            if not chunk:
                break
            login_res += chunk
            
        if "Response: Success" not in login_res:
            s.close()
            return "Login failed"
            
        # Send action
        cmd = f"Action: {action}\r\n"
        for k, v in parameters.items():
            cmd += f"{k}: {v}\r\n"
        cmd += "\r\n"
        s.sendall(cmd.encode('utf-8'))
        
        response = ""
        end_markers = ["QueueStatusComplete", "QueueSummaryComplete", "Response: Error", "Message: "]
        
        while True:
            chunk = s.recv(4096).decode('utf-8', errors='ignore')
            if not chunk:
                break
            response += chunk
            if action in ["QueueStatus", "QueueSummary"]:
                if any(marker in response for marker in end_markers):
                    break
            else:
                if "\r\n\r\n" in response:
                    break
                    
        # Logoff
        s.sendall("Action: Logoff\r\n\r\n".encode('utf-8'))
        s.close()
        return response
    except Exception as e:
        return f"Error: {e}"

def get_live_queue_status():
    try:
        import rcm_queue_db
        status = rcm_queue_db.get_live_dashboard_status()
        return status.get("queues", {})
    except Exception as e:
        print(f"Error getting live queue status from database: {e}")
        return {}

def get_asterisk_db_features():
    # Runs "asterisk -rx 'database show'" and parses DND and Forwarding configurations.
    features = {}
    try:
        output = run_asterisk_cmd("database show")
        if not output or "Error" in output or output.startswith("Error"):
            return {}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" not in line:
                continue
            parts = line.split(":", 1)
            key, val = parts[0].strip(), parts[1].strip()
            # Key format like: /FORWARD/ALWAYS/4321 or /DND/5001
            key_parts = [p for p in key.split("/") if p]
            if len(key_parts) >= 2:
                feat_type = key_parts[0] # "FORWARD" or "DND"
                if feat_type == "DND" and len(key_parts) == 2:
                    ext = key_parts[1]
                    if ext not in features:
                        features[ext] = {}
                    features[ext]["dnd"] = val # "on" or "off"
                elif feat_type == "FORWARD" and len(key_parts) == 3:
                    fwd_type = key_parts[1] # "ALWAYS", "BUSY", "NOANSWER", "UNAVAIL"
                    ext = key_parts[2]
                    if ext not in features:
                        features[ext] = {}
                    if "forward" not in features[ext]:
                        features[ext]["forward"] = {}
                    features[ext]["forward"][fwd_type.lower()] = val
    except Exception as e:
        print(f"Error getting asterisk db features: {e}")
    return features

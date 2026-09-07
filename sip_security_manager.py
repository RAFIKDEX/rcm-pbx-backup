import sqlite3
import json
import subprocess
import os
from datetime import datetime, timezone
import ipaddress
import db

def get_db():
    return db.get_db()

def _run_helper(action, data=None):
    cmd = ['sudo', '/usr/local/bin/rcm_fail2ban_helper.py', action]
    try:
        proc = subprocess.run(cmd, input=json.dumps(data) if data else "", text=True, capture_output=True, check=True)
        return json.loads(proc.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Fail2ban helper error: {e.stderr}")
        return {"success": False, "error": str(e)}
    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid response from helper"}

def get_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sip_security_settings WHERE id = 1")
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"enabled": 0, "bantime_seconds": 600, "findtime_seconds": 300, "maxretry": 10}

def _helper_failure_message(result, fallback):
    return (result or {}).get('error') or (result or {}).get('output') or fallback

def set_service_enabled(enabled, username):
    """Start or stop the complete Fail2Ban service and persist its state."""
    desired = 1 if enabled else 0
    settings = get_settings()
    previous = 1 if settings.get('fail2ban_service_enabled', 1) else 0
    action = 'service_start' if desired else 'service_stop'

    service_result = _run_helper(action)
    if not service_result.get('success'):
        return False, f"Could not {'start' if desired else 'stop'} Fail2Ban: {_helper_failure_message(service_result, 'Service command failed.')}"

    if desired:
        apply_result = apply_configuration()
        if not apply_result.get('success'):
            _run_helper('service_stop')
            return False, f"Fail2Ban started but configuration reload failed: {_helper_failure_message(apply_result, 'Unknown error')}"

    conn = get_db()
    try:
        conn.execute("""
            UPDATE sip_security_settings
            SET fail2ban_service_enabled = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?
            WHERE id = 1
        """, (desired, username))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        _run_helper('service_start' if previous else 'service_stop')
        return False, f"Fail2Ban service changed but the setting could not be saved: {exc}"
    finally:
        conn.close()

    if desired:
        return True, "Fail2Ban service enabled and configuration applied."
    return True, "Fail2Ban service disabled. All Fail2Ban jails are stopped."

def save_settings(enabled, bantime, findtime, maxretry, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE sip_security_settings 
        SET enabled = ?, bantime_seconds = ?, findtime_seconds = ?, maxretry = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?
        WHERE id = 1
    """, (enabled, bantime, findtime, maxretry, username))
    conn.commit()
    conn.close()
    return True

def get_whitelists():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sip_security_whitelist ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_whitelist(value, username):
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False, "Invalid IP or CIDR format"
        
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO sip_security_whitelist (value, normalized_network, address_family, prefix_length, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (value, str(net.network_address), "IPv6" if net.version == 6 else "IPv4", net.prefixlen, username))
        conn.commit()
        success = True
        msg = "Whitelist entry added."
    except sqlite3.IntegrityError:
        success = False
        msg = "Entry already exists."
    conn.close()
    return success, msg

def remove_whitelist(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM sip_security_whitelist WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return True

def get_blacklists():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sip_security_blacklist ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_blacklist(value, duration, reason, username):
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False, "Invalid IP or CIDR format"
    
    # Check whitelist conflict
    whitelists = get_whitelists()
    for w in whitelists:
        w_net = ipaddress.ip_network(f"{w['normalized_network']}/{w['prefix_length']}", strict=False)
        if net.overlaps(w_net):
            return False, f"Conflicts with whitelist entry {w['value']}"
            
    # Add to DB
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO sip_security_blacklist 
        (value, normalized_network, address_family, prefix_length, reason, expires_at, created_by, status)
        VALUES (?, ?, ?, ?, ?, datetime('now', ? || ' seconds'), ?, 'active')
    """, (value, str(net.network_address), "IPv6" if net.version == 6 else "IPv4", net.prefixlen, reason, duration, username))
    blacklist_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # Apply to fail2ban if it's a single IP
    if net.num_addresses == 1:
        _run_helper('ban', {'ip': str(net.network_address)})
        
    return True, "Blacklist entry added."

def remove_blacklist(id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sip_security_blacklist WHERE id = ?", (id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Not found"
        
    c.execute("""
        UPDATE sip_security_blacklist 
        SET status = 'removed', removed_at = CURRENT_TIMESTAMP, removed_by = ?, removal_method = 'manual'
        WHERE id = ?
    """, (username, id))
    conn.commit()
    conn.close()
    
    net = ipaddress.ip_network(f"{row['normalized_network']}/{row['prefix_length']}", strict=False)
    if net.num_addresses == 1:
        _run_helper('unban', {'ip': str(net.network_address)})
        
    return True, "Removed."

def get_events(page=1, limit=50, search=''):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM sip_security_events"
    count_query = "SELECT COUNT(*) FROM sip_security_events"
    params = []
    
    if search:
        search_clause = " WHERE ip_address LIKE ? OR event_type LIKE ? OR description LIKE ?"
        query += search_clause
        count_query += search_clause
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    c.execute(count_query, params)
    total_count = c.fetchone()[0]
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, (page - 1) * limit])
    
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows, total_count

def generate_jail_config(settings, whitelists):
    if not settings.get('enabled'):
        return ""
        
    ignoreips = ["127.0.0.1/8", "::1"]
    for w in whitelists:
        ignoreips.append(w['value'])
        
    # We use a dedicated action to log unbans if needed, or just let fail2ban run standard actions.
    # We will use Asterisk's standard security log path or messages depending on logger.conf.
    # Usually Asterisk 20 logs to /var/log/asterisk/security.log if configured.
    
    conf = f"""
[rcm-pjsip-register]
enabled = true
port     = 5060,5061
protocol = all
filter   = rcm-pjsip-register
logpath  = /var/log/asterisk/security.log
           /var/log/asterisk/messages.log
maxretry = {settings.get('maxretry', 10)}
findtime = {settings.get('findtime_seconds', 300)}
bantime  = {settings.get('bantime_seconds', 600)}
ignoreip = {' '.join(ignoreips)}
"""
    return conf

def generate_filter_config():
    # Strict regex matching ONLY failed PJSIP REGISTER attempts.
    # We check both security.log (SecurityEvent="ChallengeResponseFailed") and messages.log formats.
    conf = """
[INCLUDES]
before = common.conf

[Definition]
failregex = ^.*SecurityEvent="ChallengeResponseFailed".*Service="PJSIP".*RemoteAddress="[A-Z0-9]+/(UDP|TCP|TLS)/<HOST>/[0-9]+".*$
            ^.*SecurityEvent="InvalidAccountID".*Service="PJSIP".*RemoteAddress="[A-Z0-9]+/(UDP|TCP|TLS)/<HOST>/[0-9]+".*$
            ^.*NOTICE.*res_pjsip/pjsip_distributor.c:.*Request 'REGISTER'.*failed for '<HOST>:[0-9]+'.*$

ignoreregex = ^.*SecurityEvent="ChallengeSent".*$
              ^.*SecurityEvent="SuccessfulAuth".*$
"""
    return conf

def apply_configuration():
    settings = get_settings()
    whitelists = get_whitelists()
    
    jail_conf = generate_jail_config(settings, whitelists)
    filter_conf = generate_filter_config()
    
    res = _run_helper('apply', {'jail_conf': jail_conf, 'filter_conf': filter_conf})
    return res

def get_status():
    return _run_helper('status')

def unban_ip(ip, username):
    res = _run_helper('unban', {'ip': ip})
    if res.get('success'):
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO sip_security_events 
            (event_type, source_ip, actor_type, actor_username, status)
            VALUES ('Manual Unban', ?, 'Administrator', ?, 'success')
        """, (ip, username))
        conn.commit()
        conn.close()
    return res

def reconcile_bans():
    # 1. Sync active bans from fail2ban to DB
    status = get_status()
    active_ips = status.get('banned_ips', [])
    
    # Log any new bans not in DB
    # For now, we will just record them if we want
    
    # 2. Expire manual blacklists
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sip_security_blacklist WHERE status = 'active' AND expires_at <= CURRENT_TIMESTAMP")
    expired = c.fetchall()
    for row in expired:
        net = ipaddress.ip_network(f"{row['normalized_network']}/{row['prefix_length']}", strict=False)
        if net.num_addresses == 1:
            _run_helper('unban', {'ip': str(net.network_address)})
            
        c.execute("""
            UPDATE sip_security_blacklist 
            SET status = 'expired', removed_at = CURRENT_TIMESTAMP, removal_method = 'automatic'
            WHERE id = ?
        """, (row['id'],))
        
        c.execute("""
            INSERT INTO sip_security_events 
            (event_type, source_ip, actor_type, status, reason)
            VALUES ('Automatic Expiry', ?, 'System', 'success', 'Blacklist expired')
        """, (row['value'],))
        
    conn.commit()
    conn.close()

import sqlite3
import json
import subprocess
import os
import ipaddress
import hashlib
from db import get_db

def get_available_interfaces():
    """Return interfaces that can safely be used in an nftables rule."""
    try:
        return sorted(i for i in os.listdir('/sys/class/net') if i and i != 'lo')
    except Exception:
        return ['eth0', 'eth1', 'ens18']

# Mocked retrieval for admin lockouts (In real-life this would query the system or PBX DB)
def get_management_ports():
    return ["22", "80", "443", "5060"]

def validate_ipv4_or_empty(ip, mask):
    if not ip and not mask:
        return True, ""
    if ip and not mask:
        mask = "255.255.255.255"
    if mask and not ip:
        return False, "Mask provided without IP"
    try:
        network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
        return True, ""
    except Exception as e:
        return False, str(e)

def validate_port_or_empty(port):
    if not port:
        return True, ""
    try:
        p = int(port)
        if 1 <= p <= 65535:
            return True, ""
    except:
        pass
    return False, "Port must be 1-65535 or empty"

def validate_rule_data(data):
    rule_name = data.get("rule_name", "").strip()
    if not rule_name:
        raise ValueError("Rule Name is required.")
        
    action = data.get("action")
    if action not in ["accept", "drop"]:
        raise ValueError("Action must be accept or drop.")
        
    direction_type = data.get("direction_type")
    if direction_type not in ["in", "out", "all"]:
        raise ValueError("Direction must be in, out, or all.")
        
    interface_name = data.get("interface_name")
    if not interface_name:
        raise ValueError("Interface is required.")
    if interface_name == "lo":
        raise ValueError("Cannot explicitly manage loopback interface here.")
        
    protocol = data.get("protocol")
    if protocol not in ["tcp", "udp", "both"]:
        raise ValueError("Protocol must be tcp, udp, or both.")

    src_ok, src_err = validate_ipv4_or_empty(data.get("source_ip"), data.get("source_subnet_mask"))
    if not src_ok:
        raise ValueError(f"Invalid Source IP/Mask: {src_err}")
        
    dst_ok, dst_err = validate_ipv4_or_empty(data.get("destination_ip"), data.get("destination_subnet_mask"))
    if not dst_ok:
        raise ValueError(f"Invalid Destination IP/Mask: {dst_err}")

    sport_ok, sport_err = validate_port_or_empty(data.get("source_port"))
    if not sport_ok:
        raise ValueError(f"Invalid Source Port: {sport_err}")

    dport_ok, dport_err = validate_port_or_empty(data.get("destination_port"))
    if not dport_ok:
        raise ValueError(f"Invalid Destination Port: {dport_err}")
        
    # Enhanced Lockout check
    if action == "drop" and direction_type in ["in", "all"]:
        mgm_ports = get_management_ports()
        if (data.get("destination_port") in mgm_ports) or (not data.get("destination_port")):
            if not data.get("source_ip"):
                raise ValueError(f"Admin lockout prevention: Cannot unconditionally drop traffic to management/PBX ports ({', '.join(mgm_ports)}).")
        if data.get("destination_ip") in ["127.0.0.1", "localhost"]:
            raise ValueError("Admin lockout prevention: Cannot drop localhost.")
            
def log_event(action, details):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO rcm_firewall_events (event_action, details) VALUES (?, ?)", (action, json.dumps(details)))
    conn.commit()
    conn.close()

def get_all_rules():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_firewall_rules ORDER BY id ASC")
    rules = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rules

def get_rule(rule_id):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_firewall_rules WHERE id = ?", (rule_id,))
    rule = cursor.fetchone()
    conn.close()
    return dict(rule) if rule else None

def add_rule(data, username="admin"):
    validate_rule_data(data)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM rcm_firewall_rules WHERE rule_name = ?", (data["rule_name"].strip(),))
    if cursor.fetchone():
        conn.close()
        raise ValueError("A rule with this name already exists.")
        
    cursor.execute("""
        SELECT id FROM rcm_firewall_rules 
        WHERE action = ? AND direction_type = ? AND interface_name = ? 
        AND COALESCE(source_ip, '') = ? AND COALESCE(source_port, '') = ? AND COALESCE(source_subnet_mask, '') = ?
        AND COALESCE(destination_ip, '') = ? AND COALESCE(destination_port, '') = ? AND COALESCE(destination_subnet_mask, '') = ?
        AND protocol = ?
    """, (
        data["action"], data["direction_type"], data["interface_name"],
        data.get("source_ip") or "", data.get("source_port") or "", data.get("source_subnet_mask") or "",
        data.get("destination_ip") or "", data.get("destination_port") or "", data.get("destination_subnet_mask") or "",
        data["protocol"]
    ))
    if cursor.fetchone():
        conn.close()
        raise ValueError("An exact duplicate rule already exists.")

    cursor.execute("""
        INSERT INTO rcm_firewall_rules (
            rule_name, action, direction_type, interface_name,
            source_ip, source_port, source_subnet_mask,
            destination_ip, destination_port, destination_subnet_mask,
            protocol, apply_status, created_by, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    """, (
        data["rule_name"].strip(), data["action"], data["direction_type"], data["interface_name"],
        data.get("source_ip") or "", data.get("source_port") or "", data.get("source_subnet_mask") or "",
        data.get("destination_ip") or "", data.get("destination_port") or "", data.get("destination_subnet_mask") or "",
        data["protocol"], username, username
    ))
    conn.commit()
    conn.close()
    log_event("Rule Created", {"rule_name": data["rule_name"], "user": username})

def edit_rule(rule_id, data, username="admin"):
    validate_rule_data(data)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM rcm_firewall_rules WHERE rule_name = ? AND id != ?", (data["rule_name"].strip(), rule_id))
    if cursor.fetchone():
        conn.close()
        raise ValueError("A rule with this name already exists.")
        
    # Preserve old details for audit
    old = get_rule(rule_id)
        
    cursor.execute("""
        UPDATE rcm_firewall_rules SET
            rule_name = ?, action = ?, direction_type = ?, interface_name = ?,
            source_ip = ?, source_port = ?, source_subnet_mask = ?,
            destination_ip = ?, destination_port = ?, destination_subnet_mask = ?,
            protocol = ?, apply_status = 'pending', updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        data["rule_name"].strip(), data["action"], data["direction_type"], data["interface_name"],
        data.get("source_ip") or "", data.get("source_port") or "", data.get("source_subnet_mask") or "",
        data.get("destination_ip") or "", data.get("destination_port") or "", data.get("destination_subnet_mask") or "",
        data["protocol"], username, rule_id
    ))
    conn.commit()
    conn.close()
    log_event("Rule Updated", {"rule_name": data["rule_name"], "rule_id": rule_id, "user": username, "old": old, "new": data})

def delete_rules(rule_ids, username="admin"):
    if not rule_ids: return
    conn = get_db()
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(rule_ids))
    cursor.execute(f"DELETE FROM rcm_firewall_rules WHERE id IN ({placeholders})", tuple(rule_ids))
    
    # Also we must set any remaining rules to pending because the DB state changed
    cursor.execute("UPDATE rcm_firewall_rules SET apply_status = 'pending'")
    
    conn.commit()
    conn.close()
    if len(rule_ids) == 1:
        log_event("Rule Deleted", {"rule_ids": rule_ids, "user": username})
    else:
        log_event("Rule Bulk Deleted", {"rule_ids": rule_ids, "user": username})

def apply_firewall(username="admin"):
    rules = get_all_rules()
    expanded = []
    
    for r in rules:
        if not r.get("enabled", 1): continue
        dirs = ["in", "out"] if r["direction_type"] == "all" else [r["direction_type"]]
        protos = ["tcp", "udp"] if r["protocol"] == "both" else [r["protocol"]]
        
        for d in dirs:
            for p in protos:
                entry = {
                    "direction": d,
                    "protocol": p,
                    "interface": r["interface_name"],
                    "action": r["action"],
                }
                
                if r["source_ip"]:
                    mask = r["source_subnet_mask"] or "255.255.255.255"
                    entry["saddr"] = f"{r['source_ip']}/{ipaddress.IPv4Network('0.0.0.0/'+mask, strict=False).prefixlen}"
                if r["source_port"]:
                    entry["sport"] = r["source_port"]
                    
                if r["destination_ip"]:
                    mask = r["destination_subnet_mask"] or "255.255.255.255"
                    entry["daddr"] = f"{r['destination_ip']}/{ipaddress.IPv4Network('0.0.0.0/'+mask, strict=False).prefixlen}"
                if r["destination_port"]:
                    entry["dport"] = r["destination_port"]
                    
                expanded.append(entry)
                
    log_event("Apply Started", {"user": username})
    
    # Pipe JSON over stdin to eliminate TOCTOU temp file risks
    payload = json.dumps(expanded)
    
    try:
        result = subprocess.run(
            ["sudo", "/usr/bin/python3", "/usr/local/bin/rcm_firewall_helper.py"],
            input=payload,
            capture_output=True, text=True
        )
        if result.returncode != 0:
            err = result.stderr or result.stdout
            log_event("Apply Failed", {"error": err, "user": username})
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE rcm_firewall_rules SET apply_status = 'error' WHERE apply_status = 'pending'")
            conn.commit()
            conn.close()
            
            raise RuntimeError(f"Firewall apply failed: {err}")
            
        # Parse return payload for the new hash
        try:
            resp = json.loads(result.stdout)
            if not resp.get("success"):
                raise Exception(resp.get("error", "Unknown error"))
        except Exception as e:
            raise RuntimeError(f"Invalid response from helper: {str(e)}")
            
        # Success
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE rcm_firewall_rules SET apply_status = 'applied' WHERE apply_status IN ('pending', 'error')")
        conn.commit()
        conn.close()
        log_event("Apply Succeeded", {"user": username})
        return True
        
    except Exception as e:
        raise e

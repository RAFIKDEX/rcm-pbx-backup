#!/usr/bin/env python3
import sys
import json
import re
import os
import subprocess

EP_FILE = "/etc/asterisk/pjsip.gui.endpoint.conf"
AUTH_FILE = "/etc/asterisk/pjsip.gui.auth.conf"
AOR_FILE = "/etc/asterisk/pjsip.gui.aor.conf"
DP_FILE = "/etc/asterisk/extensions_gui.conf"
VM_FILE = "/etc/asterisk/voicemail.conf"
FM_FILE = "/etc/asterisk/followme.conf"

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

def update_section(filepath, section_name, new_keys, remove_keys=None):
    if not os.path.exists(filepath):
        return False
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == f"[{section_name}]":
            start = i
            break
            
    if start is None:
        return False
        
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
                if m:
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
                
    out = lines[:start + 1] + new_body + lines[end:]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(out) + "\n")
    return True

def upsert_voicemail(ext, enabled, password, name):
    if not os.path.exists(VM_FILE):
        return
    with open(VM_FILE, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    new_lines = []
    in_default = False
    found = False
    vm_line = f"{ext} => {password},{name},,,"
    
    for line in lines:
        t = line.strip()
        if t.startswith('[') and t.endswith(']'):
            if in_default and not found and enabled:
                new_lines.append(vm_line)
                found = True
            in_default = (t.lower() == '[default]')
            new_lines.append(line)
            continue
            
        if in_default and re.match(r'^' + ext + r'\s*=>', t):
            if enabled:
                new_lines.append(vm_line)
                found = True
            else:
                continue
        else:
            new_lines.append(line)
            
    if in_default and not found and enabled:
        new_lines.append(vm_line)
        
    with open(VM_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_lines) + "\n")

def update_followme(ext, followme_list):
    if not os.path.exists(FM_FILE):
        return
    with open(FM_FILE, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == f"[{ext}]":
            start = i
            break
            
    if start is not None:
        for j in range(start + 1, len(lines)):
            if re.match(r'^\[[^\]]+\]$', lines[j].strip()):
                end = j
                break
        lines = lines[:start] + lines[end:]
        
    if followme_list:
        fm_block = [f"[{ext}]"]
        for row in followme_list:
            fnum = str(row.get("number", "")).strip()
            fring = int(row.get("ring", 15))
            if fnum:
                fm_block.append(f"number => {fnum},{fring}")
        lines.append("")
        lines.extend(fm_block)
        
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
            
    with open(FM_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(collapsed) + "\n")

def main():
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        fail(f"Invalid JSON input: {e}")

    ext = str(data.get("ext", "")).strip()
    enabled = bool(data.get("enabled", True))
    secret = str(data.get("secret", "")).strip()
    name = str(data.get("name", "")).strip()
    callerid_number = str(data.get("callerid_number", "")).strip()
    max_contacts = data.get("max_contacts", 3)
    max_expiration = data.get("max_expiration", 120)
    ring_time = data.get("ring_time", 60)
    record_mode = str(data.get("record_mode", "noo")).strip()
    vm_enabled = bool(data.get("vm_enabled", False))
    vm_password = str(data.get("vm_password", "1234")).strip()
    direct_media = bool(data.get("direct_media", False))
    nat = bool(data.get("nat", False))
    followme = data.get("followme", [])

    # Validation
    if not re.match(r'^\d{2,6}$', ext):
        fail("Invalid extension")
    if not secret:
        fail("Secret is required")
    if not re.match(r'^[0-9+*#]{2,20}$', callerid_number):
        fail("Invalid Caller ID number")

    # Update Endpoint
    cid_str = f'"{name}" <{callerid_number}>' if name else callerid_number
    new_ep_keys = {
        "callerid": cid_str,
        "allow": "alaw,ulaw",
        "direct_media": "yes" if direct_media else "no"
    }
    
    # Handling NAT parameters
    remove_ep_keys = []
    if nat:
        new_ep_keys["rtp_symmetric"] = "yes"
        new_ep_keys["rewrite_contact"] = "yes"
        new_ep_keys["force_rport"] = "yes"
    else:
        remove_ep_keys = ["rtp_symmetric", "rewrite_contact", "force_rport"]

    if not update_section(EP_FILE, ext, new_ep_keys, remove_ep_keys):
        fail("Failed to update endpoint configuration")

    # Update Auth
    new_auth_keys = {
        "password": secret
    }
    update_section(AUTH_FILE, ext, new_auth_keys)

    # Update Aor
    actual_max = max_contacts if enabled else 0
    new_aor_keys = {
        "rcm_max_contacts": str(max_contacts),
        "max_contacts": str(actual_max),
        "maximum_expiration": str(max_expiration)
    }
    update_section(AOR_FILE, ext, new_aor_keys)

    # Update extensions_gui.conf globals
    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            dp_lines = f.read().splitlines()
            
        new_dp_lines = []
        for line in dp_lines:
            t = line.strip()
            if t.startswith(f"RECORD_{ext}="):
                new_dp_lines.append(f"RECORD_{ext}={record_mode}")
            elif t.startswith(f"VM_{ext}="):
                new_dp_lines.append(f"VM_{ext}={'On' if vm_enabled else 'Off'}")
            elif t.startswith(f"RING_{ext}="):
                new_dp_lines.append(f"RING_{ext}={ring_time}")
            else:
                new_dp_lines.append(line)
                
        with open(DP_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_dp_lines) + "\n")

    # Update voicemail.conf
    vm_display_name = name if name else ext
    upsert_voicemail(ext, vm_enabled, vm_password, vm_display_name)

    # Update followme.conf
    update_followme(ext, followme)

    # Reload Asterisk configs
    subprocess.run(["/usr/sbin/asterisk", "-rx", "pjsip reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/usr/sbin/asterisk", "-rx", "dialplan reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"OK: Edited extension {ext}")

if __name__ == "__main__":
    main()

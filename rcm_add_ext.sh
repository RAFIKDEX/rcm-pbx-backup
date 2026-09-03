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
CTX_FILE = "/etc/asterisk/context_exten.conf"
VM_FILE = "/etc/asterisk/voicemail.conf"
FM_FILE = "/etc/asterisk/followme.conf"

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

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
    try:
        max_contacts = int(max_contacts)
        if max_contacts < 1 or max_contacts > 10:
            raise ValueError
    except Exception:
        fail("Invalid concurrent registrations (must be 1-10)")
    try:
        max_expiration = int(max_expiration)
        ring_time = int(ring_time)
    except Exception:
        fail("Invalid expiration or ring time")
    if record_mode not in ["noo", "in", "out", "all"]:
        fail("Invalid record mode")
    if vm_enabled and not re.match(r'^\d+$', vm_password):
        fail("Voicemail password must be digits only")

    # Check duplicates in pjsip config files
    for filepath in [EP_FILE, AUTH_FILE, AOR_FILE]:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                if f"[{ext}]" in content:
                    fail(f"Extension [{ext}] already exists in {os.path.basename(filepath)}")

    # Check duplicates in extensions_gui
    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if f"RECORD_{ext}=" in content or f"VM_{ext}=" in content:
                fail(f"Extension [{ext}] dialplan entries already exist in extensions_gui.conf")

    # 1. pjsip.gui.endpoint.conf
    cid_str = f'callerid="{name}" <{callerid_number}>' if name else f'callerid={callerid_number}'
    ep_block = f"""
[{ext}]
type=endpoint
context=from-internal-{ext}
{cid_str}
disallow=all
allow=alaw,ulaw
aors={ext}
auth={ext}
transport=transport-udp
direct_media={'yes' if direct_media else 'no'}
"""
    if nat:
        ep_block += """rtp_symmetric=yes
rewrite_contact=yes
force_rport=yes
"""
    with open(EP_FILE, 'a', encoding='utf-8') as f:
        f.write(ep_block + "\n")

    # 2. pjsip.gui.auth.conf
    auth_block = f"""
[{ext}]
type=auth
auth_type=userpass
username={ext}
password={secret}
"""
    with open(AUTH_FILE, 'a', encoding='utf-8') as f:
        f.write(auth_block + "\n")

    # 3. pjsip.gui.aor.conf
    actual_max = max_contacts if enabled else 0
    aor_block = f"""
[{ext}]
type=aor
; rcm_max_contacts={max_contacts}
max_contacts={actual_max}
remove_existing=yes
qualify_frequency=60
maximum_expiration={max_expiration}
"""
    with open(AOR_FILE, 'a', encoding='utf-8') as f:
        f.write(aor_block + "\n")

    # 4. extensions_gui.conf
    # We update both globals and internal section in-place
    globals_updated = False
    internal_updated = False
    
    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    else:
        lines = ["[globals]", "", "[internal]"]

    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip() == "[globals]" and not globals_updated:
            new_lines.append(f"RECORD_{ext}={record_mode}")
            new_lines.append(f"VM_{ext}={'On' if vm_enabled else 'Off'}")
            new_lines.append(f"RING_{ext}={ring_time}")
            globals_updated = True
        if line.strip() == "[internal]" and not internal_updated:
            new_lines.append(f"exten => {ext},1,Goto(dexter,${{EXTEN}},1)")
            internal_updated = True

    if not globals_updated:
        new_lines.extend(["", "[globals]", f"RECORD_{ext}={record_mode}", f"VM_{ext}={'On' if vm_enabled else 'Off'}", f"RING_{ext}={ring_time}"])
    if not internal_updated:
        new_lines.extend(["", "[internal]", f"exten => {ext},1,Goto(dexter,${{EXTEN}},1)"])

    with open(DP_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_lines) + "\n")

    # 5. context_exten.conf
    ctx_block = f"""
[from-internal-{ext}]
include => internal
; RCM-OUT-START
; RCM-OUT-END
"""
    with open(CTX_FILE, 'a', encoding='utf-8') as f:
        f.write(ctx_block + "\n")

    # 6. voicemail.conf
    if vm_enabled:
        vm_display_name = name if name else ext
        vm_line = f"{ext} => {vm_password},{vm_display_name},,,"
        
        # Read file, insert line under [default]
        if os.path.exists(VM_FILE):
            with open(VM_FILE, 'r', encoding='utf-8') as f:
                vm_lines = f.read().splitlines()
        else:
            vm_lines = ["[general]", "", "[default]"]
            
        new_vm_lines = []
        vm_inserted = False
        in_default = False
        for line in vm_lines:
            new_vm_lines.append(line)
            if line.strip().startswith("[default]"):
                in_default = True
            elif in_default and not vm_inserted and (line.strip() == "" or line.strip().startswith("[")):
                # Insert before next section or at end of default section
                if line.strip().startswith("["):
                    new_vm_lines.insert(-1, vm_line)
                    vm_inserted = True
                    in_default = False
        if in_default and not vm_inserted:
            new_vm_lines.append(vm_line)
            vm_inserted = True
            
        with open(VM_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_vm_lines) + "\n")

    # 7. followme.conf
    if followme:
        fm_block = f"\n[{ext}]\n"
        for row in followme:
            fnum = str(row.get("number", "")).strip()
            fring = int(row.get("ring", 15))
            if fnum:
                fm_block += f"number => {fnum},{fring}\n"
        with open(FM_FILE, 'a', encoding='utf-8') as f:
            f.write(fm_block + "\n")

    # Reload Asterisk configs
    subprocess.run(["/usr/sbin/asterisk", "-rx", "pjsip reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/usr/sbin/asterisk", "-rx", "dialplan reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"OK: Added extension {ext}")

if __name__ == "__main__":
    main()

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
        
    # Collapse multiple consecutive blank lines
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

def delete_voicemail(ext):
    if not os.path.exists(VM_FILE):
        return
    with open(VM_FILE, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    new_lines = []
    in_default = False
    for line in lines:
        t = line.strip()
        if t.startswith('[') and t.endswith(']'):
            in_default = (t.lower() == '[default]')
            new_lines.append(line)
            continue
            
        if in_default and re.match(r'^' + ext + r'\s*=>', t):
            continue
        else:
            new_lines.append(line)
            
    with open(VM_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_lines) + "\n")

def main():
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        fail(f"Invalid JSON input: {e}")

    ext = str(data.get("ext", "")).strip()
    if not re.match(r'^\d{2,6}$', ext):
        fail("Invalid extension")

    # Delete from PJSIP files
    delete_section(EP_FILE, ext)
    delete_section(AUTH_FILE, ext)
    delete_section(AOR_FILE, ext)

    # Delete from extensions_gui.conf
    if os.path.exists(DP_FILE):
        with open(DP_FILE, 'r', encoding='utf-8') as f:
            dp_lines = f.read().splitlines()
            
        new_dp_lines = []
        for line in dp_lines:
            t = line.strip()
            if t.startswith(f"RECORD_{ext}="):
                continue
            if t.startswith(f"VM_{ext}="):
                continue
            if t.startswith(f"RING_{ext}="):
                continue
            if t.startswith(f"exten => {ext},"):
                continue
            new_dp_lines.append(line)
            
        # Collapse multiple consecutive blank lines
        collapsed = []
        prev_blank = False
        for line in new_dp_lines:
            if line.strip() == "":
                if not prev_blank:
                    collapsed.append(line)
                    prev_blank = True
            else:
                collapsed.append(line)
                prev_blank = False
                
        with open(DP_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(collapsed) + "\n")

    # Delete from context_exten.conf
    delete_section(CTX_FILE, f"from-internal-{ext}")

    # Delete voicemail
    delete_voicemail(ext)

    # Delete Follow Me
    delete_section(FM_FILE, ext)

    # Reload Asterisk configs
    subprocess.run(["/usr/sbin/asterisk", "-rx", "pjsip reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/usr/sbin/asterisk", "-rx", "dialplan reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"OK: Deleted extension {ext}")

if __name__ == "__main__":
    main()

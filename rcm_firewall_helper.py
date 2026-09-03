#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import tempfile
import hashlib

NFT_CONF_DIR = "/etc/nftables.d"
NFT_CONF_FILE = os.path.join(NFT_CONF_DIR, "rcm-firewall.nft")

def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({"success": False, "error": "No input received"}))
            sys.exit(1)
        rules = json.loads(input_data)
    except Exception as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON on stdin: {e}"}))
        sys.exit(1)

    # Validate json schema
    if not isinstance(rules, list):
        print(json.dumps({"success": False, "error": "Expected JSON list"}))
        sys.exit(1)

    # Build nft script
    nft_script = []
    # Guarantee table exists, then flush it
    nft_script.append("table inet rcm-firewall { }")
    nft_script.append("flush table inet rcm-firewall")
    
    nft_script.append("table inet rcm-firewall {")
    nft_script.append("    chain input {")
    nft_script.append("        type filter hook input priority filter - 5; policy accept;")
    for r in [x for x in rules if x['direction'] == 'in']:
        line = "        "
        if r.get('interface'): line += f"iifname \"{r['interface']}\" "
        if r.get('saddr'): line += f"ip saddr {r['saddr']} "
        if r.get('daddr'): line += f"ip daddr {r['daddr']} "
        if r.get('protocol'): line += f"meta l4proto {r['protocol']} "
        if r.get('sport'): line += f"{r['protocol']} sport {r['sport']} "
        if r.get('dport'): line += f"{r['protocol']} dport {r['dport']} "
        line += r['action']
        nft_script.append(line)
    nft_script.append("    }")
    
    nft_script.append("    chain output {")
    nft_script.append("        type filter hook output priority filter - 5; policy accept;")
    for r in [x for x in rules if x['direction'] == 'out']:
        line = "        "
        if r.get('interface'): line += f"oifname \"{r['interface']}\" "
        if r.get('saddr'): line += f"ip saddr {r['saddr']} "
        if r.get('daddr'): line += f"ip daddr {r['daddr']} "
        if r.get('protocol'): line += f"meta l4proto {r['protocol']} "
        if r.get('sport'): line += f"{r['protocol']} sport {r['sport']} "
        if r.get('dport'): line += f"{r['protocol']} dport {r['dport']} "
        line += r['action']
        nft_script.append(line)
    nft_script.append("    }")
    nft_script.append("}")
    
    script_content = "\n".join(nft_script)
    script_hash = hashlib.sha256(script_content.encode('utf-8')).hexdigest()
    
    # Backup existing table if it exists
    backup_result = subprocess.run(["nft", "list", "table", "inet", "rcm-firewall"], capture_output=True, text=True)
    has_backup = backup_result.returncode == 0
    backup_script = backup_result.stdout if has_backup else ""
    
    fd, tmp_nft = tempfile.mkstemp(prefix="rcm_nft_")
    with os.fdopen(fd, 'w') as f:
        f.write(script_content)
        
    try:
        # Check syntax
        check = subprocess.run(["nft", "-c", "-f", tmp_nft], capture_output=True, text=True)
        if check.returncode != 0:
            print(json.dumps({"success": False, "error": f"Syntax check failed: {check.stderr}"}))
            sys.exit(1)
            
        # Apply atomically
        apply = subprocess.run(["nft", "-f", tmp_nft], capture_output=True, text=True)
        if apply.returncode != 0:
            if has_backup:
                r_fd, r_nft = tempfile.mkstemp(prefix="rcm_nft_rb_")
                with os.fdopen(r_fd, 'w') as f:
                    f.write("flush table inet rcm-firewall\n")
                    f.write(backup_script)
                subprocess.run(["nft", "-f", r_nft])
                os.remove(r_nft)
            print(json.dumps({"success": False, "error": f"Apply failed: {apply.stderr}"}))
            sys.exit(1)
            
        # Persist safely
        if not os.path.exists(NFT_CONF_DIR):
            os.makedirs(NFT_CONF_DIR, mode=0o755)
        with open(NFT_CONF_FILE, 'w') as f:
            f.write(script_content)
            
        # Update main config safely
        main_conf = "/etc/nftables.conf"
        include_line = 'include "/etc/nftables.d/*.nft"\n'
        
        if os.path.exists(main_conf):
            with open(main_conf, 'r') as f:
                content = f.read()
            if 'include "/etc/nftables.d/*.nft"' not in content:
                # Use atomic replacement for nftables.conf to avoid partial writes
                fd_main, tmp_main = tempfile.mkstemp(dir=os.path.dirname(main_conf))
                with os.fdopen(fd_main, 'w') as f:
                    f.write(content)
                    if not content.endswith('\n'):
                        f.write('\n')
                    f.write(include_line)
                os.chmod(tmp_main, 0o644)
                os.rename(tmp_main, main_conf)
                
        print(json.dumps({"success": True, "hash": script_hash, "script": script_content}))
    finally:
        if os.path.exists(tmp_nft):
            os.remove(tmp_nft)

if __name__ == "__main__":
    main()

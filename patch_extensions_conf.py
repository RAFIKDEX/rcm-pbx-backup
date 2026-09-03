import os

filepath = "/etc/asterisk/extensions.conf"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Normalize line endings
content = content.replace("\r\n", "\n")

# 1. Replace [forward-busy]
old_busy = """[forward-busy]
exten => _X.,1,Set(FWD_NUM_B=${SHELL(mysql -u root -p'admin' asteriskcdr -Nse "SELECT value FROM feature_actions WHERE ext='${EXTEN}' AND feature='FWD_BUSY' AND action='SET' LIMIT 1" 2>/dev/null)})
 same => n,Set(FWD_NUM_B=${FILTER(0-9,${FWD_NUM_B})})
 same => n,GotoIf($["${FWD_NUM_B}"=""]?busy,${EXTEN},1)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_B},1)"""

# Try with different variations of spacing/newlines
new_busy = """[forward-busy]
exten => _X.,1,Set(FWD_NUM_B=${DB(FORWARD/BUSY/${EXTEN})})
 same => n,GotoIf($["${FWD_NUM_B}"=""]?busy,${EXTEN},1)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_B},1)"""

# 2. Replace [forward-noanswer]
old_noanswer = """[forward-noanswer]
exten => _X.,1,Set(FWD_NUM_N=${SHELL(mysql -u root -p'admin' asteriskcdr -Nse "SELECT value FROM feature_actions WHERE ext='${EXTEN}' AND feature='FWD_NOANSWER' AND action='SET' LIMIT 1" 2>/dev/null)})
 same => n,Set(FWD_NUM_N=${FILTER(0-9,${FWD_NUM_N})})
 same => n,GotoIf($["${FWD_NUM_N}"=""]?noanswer,${EXTEN},1)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_N},1)"""

new_noanswer = """[forward-noanswer]
exten => _X.,1,Set(FWD_NUM_N=${DB(FORWARD/NOANSWER/${EXTEN})})
 same => n,GotoIf($["${FWD_NUM_N}"=""]?noanswer,${EXTEN},1)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_N},1)"""

# 3. Replace [forward-unavail]
old_unavail = """[forward-unavail]
exten => _X.,1,Set(FWD_NUM_u=${SHELL(mysql -u root -p'admin' asteriskcdr -Nse "SELECT value FROM feature_actions WHERE ext='${EXTEN}' AND feature='FWD_UNAVAIL' AND action='SET' LIMIT 1" 2>/dev/null)})
 same => n,Set(FWD_NUM_u=${FILTER(0-9,${FWD_NUM_u})})
 same => n,GotoIf($["${FWD_NUM_u}"=""]?hangup_call)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_u},1)
 same => n(hangup_call),Hangup()"""

new_unavail = """[forward-unavail]
exten => _X.,1,Set(FWD_NUM_u=${DB(FORWARD/UNAVAIL/${EXTEN})})
 same => n,GotoIf($["${FWD_NUM_u}"=""]?hangup_call)
 same => n,Goto(from-internal-${EXTEN},${FWD_NUM_u},1)
 same => n(hangup_call),Hangup()"""

# 4. Replace [unavail-fallback]
old_fallback = """[unavail-fallback]
exten => _X.,1,NoOp(Extension ${EXTEN} is unavailable)
 same => n,Set(UNAVAIL_MSG=${SHELL(python3 -c "print(next((p['path'].split('/sounds/')[-1].split('.')[0] for p in __import__('json').load(open('/etc/asterisk/rcm_media_center.json')).get('prompts', []) if p.get('name') == 'extension_unavailable' or p.get('id') == 'extension_unavailable'), 'is-curntly-unavail') if __import__('os').path.exists('/etc/asterisk/rcm_media_center.json') else 'is-curntly-unavail')", end="")})
 same => n,Playback(${UNAVAIL_MSG})
 same => n,GotoIf($["${TOLOWER(${VM_${EXTEN}})}" = "on"]?vm,${EXTEN},1)
 same => n,Goto(forward-unavail,${EXTEN},1)"""

new_fallback = """[unavail-fallback]
exten => _X.,1,NoOp(Extension ${EXTEN} is unavailable)
 same => n,Set(FWD_UNAVAIL=${DB(FORWARD/UNAVAIL/${EXTEN})})
 same => n,GotoIf($["${FWD_UNAVAIL}" != ""]?forward_unavail)
 same => n,Set(UNAVAIL_MSG=${SHELL(python3 -c "print(next((p['path'].split('/sounds/')[-1].split('.')[0] for p in __import__('json').load(open('/etc/asterisk/rcm_media_center.json')).get('prompts', []) if p.get('name') == 'extension_unavailable' or p.get('id') == 'extension_unavailable'), 'is-curntly-unavail') if __import__('os').path.exists('/etc/asterisk/rcm_media_center.json') else 'is-curntly-unavail')", end="")})
 same => n,Playback(${UNAVAIL_MSG})
 same => n,GotoIf($["${TOLOWER(${VM_${EXTEN}})}" = "on"]?vm,${EXTEN},1)
 same => n,Hangup()
 same => n(forward_unavail),Goto(from-internal-${EXTEN},${FWD_UNAVAIL},1)"""

def replace_fuzzy(text, old_block, new_block):
    # Strip whitespace to match regardless of exact formatting
    old_normalized = "\n".join([line.strip() for line in old_block.splitlines() if line.strip()])
    
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        # Try to find matching block of lines
        cand_lines = []
        j = i
        while len(cand_lines) < len(old_block.splitlines()) and j < len(lines):
            if lines[j].strip():
                cand_lines.append(lines[j].strip())
            j += 1
        cand_normalized = "\n".join(cand_lines)
        if cand_normalized == old_normalized:
            # We found the match! Let's replace lines from i to j-1
            text_lines = text.splitlines()
            text_lines[i:j] = [new_block]
            return "\n".join(text_lines)
        i += 1
    
    print("WARNING: Could not find block:")
    print(old_block)
    return text

content = replace_fuzzy(content, old_busy, new_busy)
content = replace_fuzzy(content, old_noanswer, new_noanswer)
content = replace_fuzzy(content, old_unavail, new_unavail)
content = replace_fuzzy(content, old_fallback, new_fallback)

# 5. Comment out [code] context. 
# We'll find "[code]" and replace it with:
# [code]
# ; Commented out to prevent conflict with [rcm-feature-codes]
# and strip everything until "[from-trunk]"
if "[code]" in content and "[from-trunk]" in content:
    parts = content.split("[code]")
    rest = parts[1].split("[from-trunk]")
    commented_code = "; Legacy code context commented out\n\n"
    content = parts[0] + "[code]\n" + commented_code + "[from-trunk]" + rest[1]
    print("Successfully commented out [code] context.")
else:
    print("WARNING: Could not locate [code] or [from-trunk]")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Patch complete!")

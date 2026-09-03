import subprocess
import re

res = subprocess.run("asterisk -rx \"queue show\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
print("Returncode:", res.returncode)
print("Stdout:\n", res.stdout)

queues_waiting_channels = {}
agent_states = {}

if res.returncode == 0 and res.stdout:
    current_queue = None
    in_members = False
    in_callers = False
    for line in res.stdout.split('\n'):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        if "has" in line_stripped and "calls" in line_stripped:
            parts = line_stripped.split()
            if len(parts) > 0:
                current_queue = parts[0]
                queues_waiting_channels[current_queue] = []
                in_members = False
                in_callers = False
            continue
        
        if current_queue:
            if "Members:" in line_stripped:
                in_members = True
                in_callers = False
                continue
            elif "Callers:" in line_stripped or "No Callers" in line_stripped:
                in_members = False
                in_callers = "Callers:" in line_stripped
                continue
            
            if in_members:
                parts = line_stripped.split()
                if len(parts) > 0:
                    member_name = parts[0]
                    ext = member_name.split("/")[-1].split("@")[0]
                    
                    is_paused = "paused" in line_stripped.lower()
                    
                    status = "UNKNOWN"
                    # Wait, let's print the check results
                    print(f"Parsing line: {line_stripped}")
                    print(f"Ext: {ext}, Queue: {current_queue}")
                    print(f"ringinuse in line: {'ringinuse' in line_stripped.lower()}")
                    print(f"in use in line: {'in use' in line_stripped.lower()}")
                    print(f"ringing in line: {'ringing' in line_stripped.lower()}")
                    print(f"busy in line: {'busy' in line_stripped.lower()}")
                    print(f"unavailable in line: {'unavailable' in line_stripped.lower()}")
                    print(f"not in use in line: {'not in use' in line_stripped.lower()}")
                    
                    # Correct matching hierarchy to avoid ringinuse / in use conflict
                    # Since "not in use" contains "in use", and "ringinuse" contains "in use"
                    if is_paused:
                        status = "PAUSED"
                    elif "ringing" in line_stripped.lower():
                        status = "RINGING"
                    elif "not in use" in line_stripped.lower():
                        status = "NOT IN USE"
                    elif "in use" in line_stripped.lower() or "busy" in line_stripped.lower():
                        status = "IN USE" if "in use" in line_stripped.lower() else "BUSY"
                    elif "unavailable" in line_stripped.lower() or "invalid" in line_stripped.lower():
                        status = "UNAVAILABLE"
                    elif "unknown" in line_stripped.lower():
                        status = "UNKNOWN"
                        
                    print(f"Status mapped: {status}\n")
                    agent_states[(ext, current_queue)] = status

print("Agent States Mapped:", agent_states)

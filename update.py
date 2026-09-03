import sys

with open('scratch_live.py', 'r') as f:
    new_content = f.read()

with open('rcm_queue_db.py', 'r') as f:
    lines = f.readlines()

out = []
in_target = False
replaced = False

for i, line in enumerate(lines):
    if line.startswith("def get_live_dashboard_status():"):
        in_target = True
        out.append(new_content)
        if not new_content.endswith('\n'):
            out.append('\n')
        continue
    
    if in_target:
        if line.startswith("def _queue_detail_bounds("):
            in_target = False
            out.append(line)
        continue
        
    out.append(line)

with open('rcm_queue_db.py', 'w') as f:
    f.writelines(out)

print("Replacement complete.")

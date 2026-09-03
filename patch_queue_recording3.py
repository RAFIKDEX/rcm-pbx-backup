import re

with open('/root/RCM_7021/rcm_queue_db.py', 'r') as f:
    content = f.read()

target = """                    if not rec: continue
                    candidate = os.path.join(monitor_dir, os.path.basename(rec))
                    if os.path.isfile(candidate) and os.path.getsize(candidate) > 44:
                        recording = os.path.basename(rec)
                        break
                if not recording:"""

replacement = """                    if not rec: continue
                    candidate = os.path.join(monitor_dir, os.path.basename(rec))
                    is_valid = False
                    try:
                        if os.path.isfile(candidate) and os.path.getsize(candidate) > 44: is_valid = True
                    except OSError: pass
                    if not is_valid:
                        try:
                            c = db.get_db().cursor()
                            loc = c.execute("SELECT file_size FROM recording_locations WHERE external_path LIKE ?", (f"%{os.path.basename(rec)}",)).fetchone()
                            if loc and loc[0] > 44: is_valid = True
                        except: pass
                    if is_valid:
                        recording = os.path.basename(rec)
                        break
                if not recording:"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/rcm_queue_db.py', 'w') as f:
        f.write(content)

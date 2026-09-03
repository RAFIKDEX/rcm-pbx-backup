import re

with open('/root/RCM_7021/rcm_queue_db.py', 'r') as f:
    content = f.read()

target = """            candidate = os.path.join(monitor_dir, os.path.basename(recording))
            if os.path.exists(candidate):
                try:
                    if os.path.getsize(candidate) > 44:
                        return os.path.basename(recording)
                except OSError:
                    pass"""

replacement = """            # Check local size or if it is on external storage
            candidate = os.path.join(monitor_dir, os.path.basename(recording))
            is_valid = False
            if os.path.exists(candidate):
                try:
                    if os.path.getsize(candidate) > 44: is_valid = True
                except: pass
            else:
                try:
                    c = db.get_db().cursor()
                    loc = c.execute("SELECT file_size FROM recording_locations WHERE cdr_uniqueid=? OR external_path LIKE ?", (uid, f"%{os.path.basename(recording)}")).fetchone()
                    if loc and loc[0] > 44: is_valid = True
                except: pass
                
            if is_valid: return os.path.basename(recording)"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/rcm_queue_db.py', 'w') as f:
        f.write(content)

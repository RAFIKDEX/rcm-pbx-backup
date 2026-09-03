import re

with open('/root/RCM_7021/rcm_queue_db.py', 'r') as f:
    content = f.read()

target1 = """            candidate = os.path.join(monitor_dir, os.path.basename(recording))
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 44:
                    return os.path.basename(recording)
            except OSError:
                continue"""

replacement1 = """            candidate = os.path.join(monitor_dir, os.path.basename(recording))
            is_valid = False
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 44: is_valid = True
            except OSError: pass
            if not is_valid:
                try:
                    c = db.get_db().cursor()
                    loc = c.execute("SELECT file_size FROM recording_locations WHERE cdr_uniqueid=? OR external_path LIKE ?", (row["uniqueid"], f"%{os.path.basename(recording)}")).fetchone()
                    if loc and loc[0] > 44: is_valid = True
                except: pass
            if is_valid: return os.path.basename(recording)"""

content = content.replace(target1, replacement1)

target2 = """                        candidate = os.path.join(monitor_dir, os.path.basename(rec))
                        try:
                            if os.path.isfile(candidate) and os.path.getsize(candidate) > 44:
                                recording = os.path.basename(rec)
                        except OSError:
                            pass"""

replacement2 = """                        candidate = os.path.join(monitor_dir, os.path.basename(rec))
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
                        if is_valid: recording = os.path.basename(rec)"""

content = content.replace(target2, replacement2)

with open('/root/RCM_7021/rcm_queue_db.py', 'w') as f:
    f.write(content)

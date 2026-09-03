import re

with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

target = """        if recording:
            recording_path = os.path.join("/var/spool/asterisk/monitor", os.path.basename(recording))
            if not os.path.isfile(recording_path) or os.path.getsize(recording_path) <= 44:
                recording = None
            elif not _recording_scope_allows_filename('call_records', recording):
                recording = None"""

replacement = """        if recording:
            recording_path = os.path.join("/var/spool/asterisk/monitor", os.path.basename(recording))
            is_valid = False
            if os.path.isfile(recording_path) and os.path.getsize(recording_path) > 44:
                is_valid = True
            else:
                try:
                    import sqlite3
                    c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
                    loc = c.execute("SELECT file_size FROM recording_locations WHERE cdr_uniqueid=? OR external_path LIKE ?", (r.get("uniqueid"), f"%{os.path.basename(recording)}")).fetchone()
                    if loc and loc[0] > 44: is_valid = True
                except: pass
                
            if not is_valid:
                recording = None
            elif not _recording_scope_allows_filename('call_records', recording):
                recording = None"""

if target in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/app.py', 'w') as f:
        f.write(content)

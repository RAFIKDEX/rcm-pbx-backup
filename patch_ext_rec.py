import re

with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

target = """    try:
        for filename in os.listdir(folder):"""

replacement = """    try:
        all_files = set()
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                all_files.add(filename)
        try:
            import sqlite3
            c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
            for row in c.execute("SELECT external_path FROM recording_locations WHERE external_path IS NOT NULL").fetchall():
                all_files.add(os.path.basename(row[0]))
        except: pass
        
        for filename in all_files:"""
content = content.replace(target, replacement)

target2 = """            if not owned:
                continue
            path = os.path.join(folder, filename)
            if not os.path.isfile(path):
                continue
            caller, callee = _recording_display_parties(filename, ext)
            mtime = os.path.getmtime(path)
            recordings.append({
                'filename': filename,
                'caller': caller,
                'callee': callee,
                    'date': rcm_queue_db._local_datetime_from_epoch(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'duration': _format_duration(_recording_duration(path)),
                'epoch': mtime
            })"""

replacement2 = """            if not owned:
                continue
            path = os.path.join(folder, filename)
            mtime = 0
            file_exists = os.path.isfile(path)
            
            if file_exists:
                mtime = os.path.getmtime(path)
            else:
                try:
                    import sqlite3, time
                    from datetime import datetime
                    c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
                    loc = c.execute("SELECT transferred_at FROM recording_locations WHERE external_path LIKE ?", (f"%{filename}",)).fetchone()
                    if loc and loc[0]:
                        mtime = datetime.strptime(loc[0], "%Y-%m-%d %H:%M:%S").timestamp()
                except: pass
                if mtime == 0: continue
            
            caller, callee = _recording_display_parties(filename, ext)
            dur = _recording_duration(path) if file_exists else 0 # fallback for external files
            recordings.append({
                'filename': filename,
                'caller': caller,
                'callee': callee,
                'date': rcm_queue_db._local_datetime_from_epoch(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'duration': _format_duration(dur) if dur else "--",
                'epoch': mtime
            })"""

content = content.replace(target2, replacement2)

with open('/root/RCM_7021/app.py', 'w') as f:
    f.write(content)

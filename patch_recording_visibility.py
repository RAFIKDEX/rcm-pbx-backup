import re

# 1. Patch db.py find_recording_for_cdr
with open('/root/RCM_7021/db.py', 'r') as f:
    db_content = f.read()

target_db = """def find_recording_for_cdr(uniqueid, src=None, dst=None, extra_parties=None, duration=None, billsec=None, start_time=None, end_time=None, userfield=None, skip_cache_refresh=True):
    monitor_folder = "/var/spool/asterisk/monitor"
    if not uniqueid or not os.path.isdir(monitor_folder):
        return ""
"""
new_db = """def find_recording_for_cdr(uniqueid, src=None, dst=None, extra_parties=None, duration=None, billsec=None, start_time=None, end_time=None, userfield=None, skip_cache_refresh=True):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT external_path, local_path FROM recording_locations WHERE cdr_uniqueid=?", (uniqueid,))
        loc = c.fetchone()
        if loc:
            return os.path.basename(loc['external_path'] or loc['local_path'] or "")
    except Exception:
        pass
        
    monitor_folder = "/var/spool/asterisk/monitor"
    if not uniqueid or not os.path.isdir(monitor_folder):
        return ""
"""
if target_db in db_content:
    db_content = db_content.replace(target_db, new_db)
    with open('/root/RCM_7021/db.py', 'w') as f:
        f.write(db_content)

# 2. Patch app.py _extension_recordings
with open('/root/RCM_7021/app.py', 'r') as f:
    app_content = f.read()

target_ext = """def _extension_recordings(ext):
    folder = EXTENSION_PORTAL_RECORDING_DIR
    recordings = []
    if not os.path.isdir(folder):
        return recordings"""
new_ext = """def _extension_recordings(ext):
    folder = EXTENSION_PORTAL_RECORDING_DIR
    recordings = []
    if not os.path.isdir(folder):
        pass"""
if target_ext in app_content:
    app_content = app_content.replace(target_ext, new_ext)

target_loop = """    if os.path.exists(monitor_folder):
        try:
            for f in os.listdir(monitor_folder):
                if f.endswith('.wav'):"""
new_loop = """    try:
        # Get external ones too
        all_files = set()
        if os.path.exists(monitor_folder):
            for f in os.listdir(monitor_folder):
                if f.endswith('.wav'):
                    all_files.add(f)
        try:
            import sqlite3
            c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
            for row in c.execute("SELECT external_path FROM recording_locations WHERE external_path IS NOT NULL").fetchall():
                all_files.add(os.path.basename(row[0]))
        except: pass
        for f in all_files:
            if f.endswith('.wav'):"""

app_content = app_content.replace(target_loop, new_loop)

# 3. Patch app.py call_records()
target_cr = """    folder = "/var/spool/asterisk/monitor"
    if os.path.exists(folder):
        try:
            for filename in os.listdir(folder):
                if filename.endswith(".wav"):"""
new_cr = """    folder = "/var/spool/asterisk/monitor"
    try:
        all_files = set()
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                if filename.endswith(".wav"):
                    all_files.add(filename)
        try:
            import sqlite3
            c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
            for row in c.execute("SELECT external_path FROM recording_locations WHERE external_path IS NOT NULL").fetchall():
                all_files.add(os.path.basename(row[0]))
        except: pass
        for filename in all_files:
            if filename.endswith(".wav"):"""
app_content = app_content.replace(target_cr, new_cr)

with open('/root/RCM_7021/app.py', 'w') as f:
    f.write(app_content)

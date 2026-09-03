import re

with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

# Fix call_records()
old_cr = """                     filepath = os.path.join(folder, filename)
                     mtime = os.path.getmtime(filepath)
                     
                     dt_utc = datetime.fromtimestamp(mtime, timezone.utc)
                     gmt3_time = dt_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                     
                     size_bytes = os.path.getsize(filepath)
                     
                     if size_bytes <= 44:
                         try:
                             os.remove(filepath)
                         except:
                             pass
                         continue"""
new_cr = """                     filepath = os.path.join(folder, filename)
                     mtime = 0
                     size_bytes = 0
                     
                     import sqlite3
                     try:
                         c = sqlite3.connect('/root/RCM_7021/rcm_7021.db').cursor()
                         loc = c.execute("SELECT file_size, transferred_at FROM recording_locations WHERE external_path LIKE ?", (f"%{filename}",)).fetchone()
                         if loc:
                             size_bytes = loc[0]
                             import time
                             from datetime import datetime
                             mtime = datetime.strptime(loc[1], "%Y-%m-%d %H:%M:%S").timestamp() if loc[1] else time.time()
                     except: pass
                     
                     if size_bytes == 0 and os.path.exists(filepath):
                         mtime = os.path.getmtime(filepath)
                         size_bytes = os.path.getsize(filepath)
                         if size_bytes <= 44:
                             try:
                                 os.remove(filepath)
                             except:
                                 pass
                             continue
                     elif size_bytes == 0:
                         continue
                         
                     dt_utc = datetime.fromtimestamp(mtime, timezone.utc)
                     gmt3_time = dt_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
"""
content = content.replace(old_cr, new_cr)

with open('/root/RCM_7021/app.py', 'w') as f:
    f.write(content)

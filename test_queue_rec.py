import sys
sys.path.append('/root/RCM_7021')
import rcm_queue_db
import sqlite3

uid = "1787467955.59"
conn = sqlite3.connect('/root/RCM_7021/rcm_queue.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM queue_calls WHERE uniqueid = ?", (uid,))
row = dict(c.fetchone() or {})
if row:
    print("Found row:", row['uniqueid'])
    rec = rcm_queue_db._resolve_queue_recording(row)
    print("Resolved Recording:", rec)
else:
    print("No row found.")

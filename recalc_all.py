import sqlite3
import sys
import datetime
sys.path.append('/root/RCM_7021')
from rcm_queue_db import _update_call_durations_in_db, get_db_connection

conn = get_db_connection()
c = conn.cursor()

c.execute("SELECT uniqueid FROM queue_calls WHERE status = 'ANSWERED'")
rows = c.fetchall()
count = 0
for row in rows:
    uid = row["uniqueid"]
    _update_call_durations_in_db(c, uid)
    count += 1
conn.commit()
conn.close()
print(f"Recalculated {count} calls.")

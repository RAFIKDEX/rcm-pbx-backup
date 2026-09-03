import sqlite3
import datetime
conn = sqlite3.connect('/root/RCM_7021/rcm_7021.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM cleanup_auto_config WHERE id=1 AND enabled=1")
row = c.fetchone()
print("Config row:", dict(row) if row else "None")
now = datetime.datetime.now()
print("Current time:", now.strftime('%H:%M'))
schedule_time = row['schedule_time']
print("Match?", now.strftime('%H:%M') == schedule_time)

c.execute("SELECT COUNT(*) FROM cleanup_history WHERE job_type='Auto_Cleanup' AND date(start_time) = date('now')")
print("Already ran today?", c.fetchone()[0])
conn.close()

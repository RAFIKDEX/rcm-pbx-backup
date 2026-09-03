import sqlite3
import datetime

db_path = '/root/RCM_7021/rcm_queue.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT uniqueid, answer_time FROM queue_calls WHERE answer_time IS NOT NULL")
calls = c.fetchall()

fixed_count = 0
for call in calls:
    uid = call["uniqueid"]
    ans_time = call["answer_time"]
    
    c.execute("SELECT event_type, timestamp FROM queue_agent_events WHERE uniqueid=? AND event_type IN ('HOLD', 'UNHOLD') ORDER BY timestamp ASC", (uid,))
    events = c.fetchall()
    
    valid_hold = 0
    active_hold = None
    for ev in events:
        ts = ev["timestamp"]
        if ts <= ans_time:
            continue
        
        if ev["event_type"] == "HOLD":
            active_hold = ts
        elif ev["event_type"] == "UNHOLD" and active_hold:
            try:
                h_dt = datetime.datetime.strptime(active_hold, "%Y-%m-%d %H:%M:%S")
                u_dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                valid_hold += max(0, int((u_dt - h_dt).total_seconds()))
            except:
                pass
            active_hold = None
            
    c.execute("UPDATE queue_calls SET hold_time = ? WHERE uniqueid = ?", (valid_hold, uid))
    fixed_count += 1

conn.commit()
conn.close()
print(f"Fixed {fixed_count} calls!")

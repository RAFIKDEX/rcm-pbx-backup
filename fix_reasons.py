import sqlite3
import datetime

conn = sqlite3.connect('/root/RCM_7021/rcm_queue.db')
c = conn.cursor()

# Get all PAUSE events that have reason 'Break' or empty
c.execute("SELECT rowid, agent, timestamp, reason FROM queue_agent_events WHERE event_type = 'PAUSE' AND (reason IS NULL OR reason = '' OR reason = 'Break')")
rows = c.fetchall()

updates = []
with open('/var/log/asterisk/queue_log', 'r') as f:
    for line in f:
        parts = line.strip().split('|')
        if len(parts) >= 6 and parts[4] == 'PAUSE':
            ts = int(parts[0])
            agent = parts[3].split('/')[-1] if '/' in parts[3] else parts[3]
            reason = parts[5]
            if reason and reason != "Break":
                # Find matching row in DB
                for rowid, db_agent, db_ts_str, db_reason in rows:
                    if db_agent == agent:
                        db_ts = int(datetime.datetime.strptime(db_ts_str, "%Y-%m-%d %H:%M:%S").timestamp())
                        if abs(db_ts - ts) <= 5:
                            updates.append((reason, rowid))

for reason, rowid in updates:
    c.execute("UPDATE queue_agent_events SET reason = ? WHERE rowid = ?", (reason, rowid))

conn.commit()
conn.close()
print(f"Updated {len(updates)} reasons.")

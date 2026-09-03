import sqlite3
conn = sqlite3.connect('/root/RCM_7021/rcm_7021.db')
conn.execute("ATTACH DATABASE '/root/RCM_7021/rcm_queue.db' AS qdb")
rows = conn.execute("SELECT c.uniqueid, q.queue_id FROM cdr_records c LEFT JOIN qdb.queue_calls q ON c.uniqueid = q.uniqueid LIMIT 5").fetchall()
print(rows)

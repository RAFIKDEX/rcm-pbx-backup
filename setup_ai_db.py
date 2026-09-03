import sqlite3

db_path = "/root/RCM_7021/rcm_queue.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS rcm_call_analysis (
    call_id INTEGER PRIMARY KEY,
    transcript TEXT,
    sentiment TEXT,
    summary TEXT,
    FOREIGN KEY(call_id) REFERENCES queue_calls(call_id)
)
""")
conn.commit()
conn.close()
print("AI Analysis table created.")

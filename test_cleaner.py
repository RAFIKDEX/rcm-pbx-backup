import sqlite3
import json
from cleanup_engine import CleanupEngine

# Setup fake job
conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
c = conn.cursor()
c.execute("INSERT INTO cleanup_jobs (job_type, status, progress_percent, cancel_requested) VALUES ('Test', 'Pending', 0, 0)")
job_id = c.lastrowid
conn.commit()
conn.close()

config = {
    "CDR": {"strategy": "keep_latest_records", "value": 10},
    "Recordings": {"strategy": "keep_latest_records", "value": 5},
    "Queue_Stats": {"strategy": "keep_latest_records", "value": 10},
    "Operation_Log": {"strategy": "keep_latest_records", "value": 5},
    "Zero_Config": {"strategy": "older_than_days", "value": 30}
}

engine = CleanupEngine(job_id, config)
print("Starting scan...")
engine.scan_and_analyze()
print("Stats:", engine.stats)


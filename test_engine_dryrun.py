import sys
import sqlite3
import json

sys.path.append("/root/RCM_7021")
from cleanup_engine import CleanupEngine

def test():
    # Insert a dummy job
    conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
    c = conn.cursor()
    c.execute("INSERT INTO cleanup_jobs (job_type, status) VALUES ('Test_Analyze', 'Pending')")
    job_id = c.lastrowid
    conn.commit()
    conn.close()

    config = {
        "CDR": {"strategy": "older_than_days", "value": 30},
        "Recordings": {"strategy": "older_than_days", "value": 30},
        "Queue_Stats": {"strategy": "older_than_days", "value": 30},
        "Zero_Config": {"strategy": "older_than_days", "value": 30},
        "Operation_Log": {"strategy": "keep_latest_records", "value": 100}
    }
    
    print("Testing scan_and_analyze()...")
    engine = CleanupEngine(job_id, config)
    engine.scan_and_analyze()
    print("Scan completed successfully!")
    print(json.dumps(engine.stats, indent=2))

if __name__ == "__main__":
    test()

import time
import sqlite3
import json
import traceback
import sys
import os

from cleanup_engine import CleanupEngine
MAIN_DB = "/root/RCM_7021/rcm_7021.db"

def check_and_run_auto_cleanup():
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM cleanup_auto_config WHERE id=1 AND enabled=1")
        config_row = c.fetchone()
        
        if not config_row:
            conn.close()
            return
            
        import datetime
        now = datetime.datetime.now()
        schedule_time = config_row['schedule_time']
        
        # 1. Check Scheduled Auto Cleanup
        if now.strftime('%H:%M') == schedule_time:
            c.execute("SELECT COUNT(*) FROM cleanup_history WHERE job_type='Auto_Cleanup' AND date(start_time) = date('now')")
            if True: # c.fetchone()[0] < 9999
                print(f"[AUTO-CLEANER] Triggering Auto Cleanup for {schedule_time}...")
                
                c.execute("SELECT COUNT(*) FROM cleanup_jobs WHERE status IN ('Pending', 'Running')")
                if c.fetchone()[0] > 0:
                    print("[AUTO-CLEANER] Cannot start Auto Cleanup. Another job is currently running.")
                else:
                    c.execute("INSERT INTO cleanup_jobs (job_type, status) VALUES ('Auto_Cleanup', 'Running')")
                    job_id = c.lastrowid
                    conn.commit()
                    
                    # Run engine
                    rules = json.loads(config_row['rules_json'])
                    engine = CleanupEngine(job_id, rules)
                    engine.scan_and_analyze()
                    engine.execute_cleanup()
                    print("[AUTO-CLEANER] Auto Cleanup completed.")

        # 2. Emergency Disk Cleanup Logic
        if config_row['disk_trigger_enabled'] == 1:
            import shutil
            total, used, free = shutil.disk_usage("/")
            usage = (used / total) * 100
            
            if usage >= config_row['disk_trigger_percent']:
                c.execute("SELECT COUNT(*) FROM cleanup_history WHERE job_type='Emergency_Cleanup' AND start_time >= datetime('now', '-6 hours')")
                if c.fetchone()[0] == 0:
                    c.execute("SELECT COUNT(*) FROM cleanup_jobs WHERE status IN ('Pending', 'Running')")
                    if c.fetchone()[0] == 0:
                        print(f"[AUTO-CLEANER] EMERGENCY DISK CLEANUP TRIGGERED (Usage: {usage:.1f}%)")
                        c.execute("INSERT INTO cleanup_jobs (job_type, status) VALUES ('Emergency_Cleanup', 'Running')")
                        job_id = c.lastrowid
                        conn.commit()
                        
                        rules = json.loads(config_row['rules_json'])
                        engine = CleanupEngine(job_id, rules)
                        engine.execute_emergency_cleanup(config_row['disk_target_percent'])
                        print("[AUTO-CLEANER] Emergency Cleanup completed.")
        
        conn.close()
            
    except Exception as e:
        print(f"[AUTO-CLEANER] Error: {e}")
        try:
            conn.close()
        except:
            pass

if __name__ == "__main__":
    print("[AUTO-CLEANER] Daemon started.")
    while True:
        check_and_run_auto_cleanup()
        time.sleep(60)

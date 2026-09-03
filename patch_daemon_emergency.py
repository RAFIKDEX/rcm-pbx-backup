with open('/root/RCM_7021/auto_cleaner_daemon.py', 'r') as f:
    content = f.read()

target = """    except Exception as e:
        print(f"[AUTO-CLEANER] Error: {e}")"""

emergency_daemon_logic = """
        # Emergency Disk Cleanup Logic
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
                        conn.close()
                        
                        rules = json.loads(config_row['rules_json'])
                        engine = CleanupEngine(job_id, rules)
                        engine.execute_emergency_cleanup(config_row['disk_target_percent'])
                        print("[AUTO-CLEANER] Emergency Cleanup completed.")
                        return

"""

content = content.replace(target, emergency_daemon_logic + target)

with open('/root/RCM_7021/auto_cleaner_daemon.py', 'w') as f:
    f.write(content)


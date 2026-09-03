import re

with open('/root/RCM_7021/cleanup_engine.py', 'r') as f:
    content = f.read()

emergency_logic = """
    def execute_emergency_cleanup(self, target_percent):
        import shutil, datetime, glob, os
        
        current_dt = datetime.datetime.now() - datetime.timedelta(days=365*5) # Start 5 years ago
        now = datetime.datetime.now()
        
        self.update_progress(10, {"phase": "Starting Emergency Disk Cleanup"})
        
        while current_dt < now:
            if self.check_cancel(): raise Exception("Cancelled")
            
            total, used, free = shutil.disk_usage("/")
            usage = (used / total) * 100
            
            if usage <= target_percent:
                break
                
            threshold_str = current_dt.strftime('%Y-%m-%d %H:%M:%S')
            ts_threshold = current_dt.timestamp()
            
            # Delete CDR
            if self.config.get("CDR"):
                conn = sqlite3.connect(MAIN_DB)
                c = conn.cursor()
                c.execute("DELETE FROM cdr_records WHERE start_time <= ?", (threshold_str,))
                if c.rowcount > 0:
                    self.deleted_details.setdefault("CDR", {"count": 0})["count"] += c.rowcount
                conn.commit()
                conn.close()
                
            # Delete Queue
            if self.config.get("Queue_Stats"):
                conn = sqlite3.connect(QUEUE_DB)
                c = conn.cursor()
                c.execute("DELETE FROM queue_calls WHERE entry_time <= ?", (threshold_str,))
                if c.rowcount > 0:
                    self.deleted_details.setdefault("Queue_Stats", {"count": 0})["count"] += c.rowcount
                conn.commit()
                conn.close()
                
            # Delete Recordings (Files free space immediately)
            if self.config.get("Recordings"):
                files = glob.glob(os.path.join(RECORDINGS_DIR, "*.wav"))
                for f in files:
                    try:
                        if os.path.getmtime(f) <= ts_threshold:
                            size = os.path.getsize(f)
                            os.remove(f)
                            self.freed_bytes += size
                            self.deleted_details.setdefault("Recordings", {"count": 0})["count"] += 1
                    except:
                        pass
                        
            # Advance time window by 15 days
            current_dt += datetime.timedelta(days=15)
            self.update_progress(50, {"phase": f"Emergency Cleanup: Scanning up to {current_dt.strftime('%Y-%m')}. Usage: {usage:.1f}%"})
            
        self.stats = self.deleted_details
        self.update_progress(100, {"phase": "Completed", "freed_bytes": self.freed_bytes})
        
        conn = sqlite3.connect(MAIN_DB)
        c = conn.cursor()
        c.execute("UPDATE cleanup_jobs SET status='Completed' WHERE id=?", (self.job_id,))
        conn.commit()
        conn.close()
        
        self.send_admin_report("Completed")
"""

# Insert before "def execute_cleanup(self):"
content = content.replace("    def execute_cleanup(self):", emergency_logic + "\n    def execute_cleanup(self):")

with open('/root/RCM_7021/cleanup_engine.py', 'w') as f:
    f.write(content)

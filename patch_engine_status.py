with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

# In scan_and_analyze, after self.update_progress(100, {"phase": "Completed"...}), update status to Completed
target = 'self.update_progress(100, {"phase": "Completed", "stats": self.stats})'
replacement = target + """
            conn = sqlite3.connect(MAIN_DB)
            c = conn.cursor()
            c.execute("UPDATE cleanup_jobs SET status='Completed' WHERE id=?", (self.job_id,))
            conn.commit()
            conn.close()"""

content = content.replace(target, replacement)

# Fix error handling in scan_and_analyze
target_err = 'self.update_progress(0, {"error": str(e)})'
replacement_err = target_err + """
            conn = sqlite3.connect(MAIN_DB)
            c = conn.cursor()
            c.execute("UPDATE cleanup_jobs SET status='Failed' WHERE id=?", (self.job_id,))
            conn.commit()
            conn.close()"""
content = content.replace(target_err, replacement_err)

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)

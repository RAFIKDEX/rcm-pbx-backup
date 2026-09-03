import re

with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

def replacer(match):
    return """    def record_history(self, status, error_details=""):
        conn = sqlite3.connect(MAIN_DB)
        c = conn.cursor()
        c.execute(\"\"\"
            INSERT INTO cleanup_history (job_id, job_type, user, status, start_time, end_time, config_json, summary_json, freed_bytes, error_details)
            VALUES (?, (SELECT job_type FROM cleanup_jobs WHERE id=?), ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?, ?, ?, ?)
        \"\"\", (self.job_id, self.job_id, 'admin', status, json.dumps(self.config), json.dumps(self.stats), self.freed_bytes, error_details))
        c.execute("UPDATE cleanup_jobs SET status=? WHERE id=?", (status, self.job_id))
        conn.commit()
        conn.close()"""

content = re.sub(r'    def record_history.*?conn\.close\(\)', replacer, content, flags=re.DOTALL)

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)

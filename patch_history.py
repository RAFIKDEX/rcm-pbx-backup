with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

# Fix UTC time in history
content = content.replace("datetime('now')", "datetime('now', 'localtime')")

# Fix Manual_Cleanup hardcoding
# We need to find the exact block and replace it
import re

old_block = """            INSERT INTO cleanup_history (job_id, job_type, user, status, start_time, end_time, config_json, summary_json, freed_bytes, error_details)
            VALUES (?, ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?, ?, ?, ?)
        ", (self.job_id, 'Manual_Cleanup', 'admin', status, json.dumps(self.config), json.dumps(self.stats), self.freed_bytes, error_details))"""

new_block = """            INSERT INTO cleanup_history (job_id, job_type, user, status, start_time, end_time, config_json, summary_json, freed_bytes, error_details)
            VALUES (?, (SELECT job_type FROM cleanup_jobs WHERE id=?), ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?, ?, ?, ?)
        ", (self.job_id, self.job_id, 'admin', status, json.dumps(self.config), json.dumps(self.stats), self.freed_bytes, error_details))"""

content = content.replace(old_block, new_block)

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)


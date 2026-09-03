import re

with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

target = 'c.execute("UPDATE cleanup_jobs SET status=? WHERE id=?", (status, self.job_id))'
replacement = target + '\n        self.send_admin_report(status, error_details)'
if 'self.send_admin_report(status, error_details)' not in content:
    content = content.replace(target, replacement)
    
with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)


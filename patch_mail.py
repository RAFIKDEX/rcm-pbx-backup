import re

with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

# Make sure we don't add it multiple times
if "def send_admin_report" not in content:
    imports = "import traceback\nimport mail_service"
    content = content.replace("import traceback", imports)

    mail_logic = """
    def send_admin_report(self, status, error_details=""):
        try:
            conn = sqlite3.connect(MAIN_DB)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT cdr_report_email FROM mail_settings WHERE id=1")
            row = c.fetchone()
            conn.close()
            
            if not row or not row['cdr_report_email']:
                return
            
            admin_email = row['cdr_report_email']
            
            # Determine Job Type
            conn = sqlite3.connect(MAIN_DB)
            c = conn.cursor()
            c.execute("SELECT job_type FROM cleanup_jobs WHERE id=?", (self.job_id,))
            jtype_row = c.fetchone()
            conn.close()
            jtype = jtype_row[0] if jtype_row else "Cleanup"
            
            freed_mb = round(self.freed_bytes / (1024*1024), 2)
            
            subject = f"RCM PBX {jtype} - {status}"
            body = f"<h2>RCM PBX Cleanup Report</h2><p><strong>Status:</strong> {status}</p>"
            if error_details:
                body += f"<p><strong>Error Details:</strong> {error_details}</p>"
            
            body += f"<p><strong>Freed Storage:</strong> {freed_mb} MB</p>"
            body += "<h3>Cleanup Statistics:</h3><ul>"
            for cat, stat in self.stats.items():
                body += f"<li><strong>{cat}:</strong> {stat.get('count', 0)} items deleted (Oldest: {stat.get('oldest', '-')})</li>"
            body += "</ul><p><em>Generated automatically by RCM PBX Cleanup Engine.</em></p>"
            
            mail_service.send_email(
                receiver_email=admin_email,
                subject=subject,
                body=body,
                feature='Cleanup',
                is_html=True
            )
        except Exception as e:
            print(f"[CleanupEngine] Failed to send admin report: {e}")
"""
    content += mail_logic

    # Call it inside record_history
    target = 'c.execute("UPDATE cleanup_jobs SET status=? WHERE id=?", (status, self.job_id))'
    replacement = target + '\n        self.send_admin_report(status, error_details)'
    content = content.replace(target, replacement)

    with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
        f.write(content)

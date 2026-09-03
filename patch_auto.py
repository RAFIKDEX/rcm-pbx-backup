with open("/root/RCM_7021/templates/cleanup_auto.html", "r") as f:
    content = f.read()

rules_js = """            "Recordings": {"enabled": true, "strategy": "older_than_days", "value": document.getElementById('retention_days').value},
            "Operation_Log": {"enabled": true, "strategy": "older_than_days", "value": document.getElementById('retention_days').value},
            "Zero_Config": {"enabled": true, "strategy": "older_than_days", "value": 30},"""

content = content.replace('            "Recordings": {"enabled": true, "strategy": "older_than_days", "value": document.getElementById(\'retention_days\').value},\n            "Zero_Config": {"enabled": true, "strategy": "older_than_days", "value": 30},', rules_js)

with open("/root/RCM_7021/templates/cleanup_auto.html", "w") as f:
    f.write(content)

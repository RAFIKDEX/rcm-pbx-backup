import re
import os

# 1. Remove from Dashboard HTML
dashboard_path = '/root/RCM_7021/templates/ext_storage_dashboard.html'
with open(dashboard_path, 'r') as f:
    content = f.read()

# Remove the link
link_target = """        <a href="{{ url_for('ext_storage_bp.job_history') }}" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: white; padding: 0.5rem 1rem; border-radius: 8px; text-decoration: none;"><i class="fa-solid fa-list-check"></i> Jobs History</a>"""
content = content.replace(link_target, "")

# Remove the Recent Export Jobs table
table_target = r"""<h3 style="color: white; margin-bottom: 20px;">Recent Export Jobs</h3>\s*<table.*?</table>"""
content = re.sub(table_target, "", content, flags=re.DOTALL)

with open(dashboard_path, 'w') as f:
    f.write(content)

# 2. Remove route from backend
routes_path = '/root/RCM_7021/external_storage_routes.py'
with open(routes_path, 'r') as f:
    content = f.read()

route_target = r"""@ext_storage_bp\.route\('/jobs'\).*?return render_template\('ext_storage_jobs\.html', jobs=jobs\)"""
content = re.sub(route_target, "", content, flags=re.DOTALL)

with open(routes_path, 'w') as f:
    f.write(content)

# 3. Delete ext_storage_jobs.html
try:
    os.remove('/root/RCM_7021/templates/ext_storage_jobs.html')
except:
    pass


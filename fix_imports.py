import os
import re
import glob

templates = [
    "announcement_list.html",
    "call_routes.html",
    "inbound_routes_list.html",
    "ivr_list.html",
    "paging_list.html",
    "pickup_groups_list.html",
    "privileges_management.html",
    "queue_list.html",
    "ringgroup_list.html",
    "speed_dial_list.html",
    "trunks.html",
    "users_management.html"
]

pattern = re.compile(
    r'<form[^>]*action="\{\{\s*url_for\(\'([^\']+)\'\)\s*\}\}"[^>]*>.*?</form>',
    re.IGNORECASE | re.DOTALL
)

for t in templates:
    path = os.path.join("templates", t)
    if not os.path.exists(path):
        continue
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    def repl(m):
        url_for_name = m.group(1)
        # Only replace if it contains this.form.submit
        if "this.form.submit" in m.group(0):
            return f'<button type="button" class="btn btn-secondary" onclick="openUniversalImportModal(\'{{{{ url_for(\'{url_for_name}\') }}}}\')"><i class="fa-solid fa-file-arrow-up"></i> Import</button>'
        return m.group(0)
    
    new_content = pattern.sub(repl, content)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {path}")

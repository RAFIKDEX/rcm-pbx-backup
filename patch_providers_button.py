import re

filepath = "/root/RCM_7021/templates/ext_storage_providers.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    <div>
        <a href="{{ url_for\('ext_storage_bp\.dashboard'\) }}" class="neu-button"><i class="fa-solid fa-arrow-left"></i> Back to Dashboard</a>
    </div>"""

replacement = """    <div>
        <a href="{{ url_for('ext_storage_bp.dashboard') }}" style="background: rgba(148, 163, 184, 0.1); border: 1px solid rgba(148, 163, 184, 0.5); color: #e2e8f0; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.2s;" onmouseover="this.style.background='rgba(148, 163, 184, 0.2)'" onmouseout="this.style.background='rgba(148, 163, 184, 0.1)'"><i class="fa-solid fa-arrow-left"></i> Back to Dashboard</a>
    </div>"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

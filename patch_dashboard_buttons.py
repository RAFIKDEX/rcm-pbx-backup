import re

filepath = "/root/RCM_7021/templates/ext_storage_dashboard.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    <div>
        <a href="{{ url_for\('ext_storage_bp\.storage_strategy'\) }}" class="neu-button btn-info"><i class="fa-solid fa-route"></i> Routing Strategy</a>
        <a href="{{ url_for\('ext_storage_bp\.providers_list'\) }}" class="neu-button btn-success"><i class="fa-solid fa-plus"></i> Add Provider</a>
    </div>"""

replacement = """    <div style="display: flex; gap: 10px;">
        <a href="{{ url_for('ext_storage_bp.storage_strategy') }}" style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.5); color: #10b981; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.2s;" onmouseover="this.style.background='rgba(16, 185, 129, 0.2)'" onmouseout="this.style.background='rgba(16, 185, 129, 0.1)'"><i class="fa-solid fa-route"></i> Routing Strategy</a>
        <a href="{{ url_for('ext_storage_bp.providers_list') }}" style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.5); color: #3b82f6; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.2s;" onmouseover="this.style.background='rgba(59, 130, 246, 0.2)'" onmouseout="this.style.background='rgba(59, 130, 246, 0.1)'"><i class="fa-solid fa-plus"></i> Add Provider</a>
    </div>"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

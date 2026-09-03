import re

filepath = "/root/RCM_7021/templates/ext_storage_strategy.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""<div style="background: linear-gradient\(135deg, rgba\(59, 130, 246, 0.1\) 0%, rgba\(15, 23, 42, 0.8\) 100%\); border: 1px solid rgba\(59, 130, 246, 0.2\); border-radius: 16px; padding: 2rem; margin-bottom: 2rem;">
    <h1 style="margin: 0; color: #f8fafc; font-size: 1.8rem; font-weight: 700;"><i class="fa-solid fa-route" style="color: #3b82f6; margin-right: 10px;"></i> Master Storage Strategy</h1>
    <p style="color: #94a3b8; margin-top: 0.5rem; font-size: 0.95rem;">Configure exactly where all new call recordings should be saved permanently.</p>
</div>"""

replacement = """<div class="content-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(15, 23, 42, 0.8) 100%); border: 1px solid rgba(59, 130, 246, 0.2); border-radius: 16px; padding: 2rem;">
    <div>
        <h1 style="margin: 0; color: #f8fafc; font-size: 1.8rem; font-weight: 700;"><i class="fa-solid fa-route" style="color: #3b82f6; margin-right: 10px;"></i> Master Storage Strategy</h1>
        <p style="color: #94a3b8; margin-top: 0.5rem; font-size: 0.95rem;">Configure exactly where all new call recordings should be saved permanently.</p>
    </div>
    <div>
        <a href="{{ url_for('ext_storage_bp.dashboard') }}" style="background: rgba(148, 163, 184, 0.1); border: 1px solid rgba(148, 163, 184, 0.5); color: #e2e8f0; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.2s;" onmouseover="this.style.background='rgba(148, 163, 184, 0.2)'" onmouseout="this.style.background='rgba(148, 163, 184, 0.1)'"><i class="fa-solid fa-arrow-left"></i> Back to Dashboard</a>
    </div>
</div>"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

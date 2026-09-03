with open('/root/RCM_7021/templates/cleanup_auto.html', 'r') as f:
    content = f.read()

target = """        <h3 style="color: white; margin-top: 30px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px;">Categories & Rules</h3>"""

emergency_html = """
        <h3 style="color: #f59e0b; margin-top: 30px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px;">Emergency Disk Space Cleanup</h3>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 15px;">Automatically trigger cleanup if server storage reaches a critical limit. It will incrementally delete the oldest records across enabled categories until the target space is reached.</p>
        
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
            <div style="display: flex; gap: 20px;">
                <div style="flex: 1;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Enable Emergency Cleanup</label>
                    <select id="disk_trigger_enabled" style="width: 100%; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
                        <option value="0" {% if config.disk_trigger_enabled == 0 %}selected{% endif %}>Disabled</option>
                        <option value="1" {% if config.disk_trigger_enabled == 1 %}selected{% endif %}>Enabled</option>
                    </select>
                </div>
                <div style="flex: 1;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Trigger When Storage Reaches (%)</label>
                    <input type="number" id="disk_trigger_percent" value="{{ config.disk_trigger_percent|default(90) }}" min="50" max="99" style="width: 100%; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
                </div>
                <div style="flex: 1;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Delete Until Storage Reaches (%)</label>
                    <input type="number" id="disk_target_percent" value="{{ config.disk_target_percent|default(75) }}" min="30" max="95" style="width: 100%; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
                </div>
            </div>
        </div>

"""

content = content.replace(target, emergency_html + target)

# Also update the JS payload
target_js = """        schedule_time: document.getElementById('schedule_time').value,
        rules: rules
    };"""

new_js = """        schedule_time: document.getElementById('schedule_time').value,
        disk_trigger_enabled: parseInt(document.getElementById('disk_trigger_enabled').value),
        disk_trigger_percent: parseInt(document.getElementById('disk_trigger_percent').value),
        disk_target_percent: parseInt(document.getElementById('disk_target_percent').value),
        rules: rules
    };"""
content = content.replace(target_js, new_js)

with open('/root/RCM_7021/templates/cleanup_auto.html', 'w') as f:
    f.write(content)

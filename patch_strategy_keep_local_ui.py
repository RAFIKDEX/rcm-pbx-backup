with open('/root/RCM_7021/templates/ext_storage_strategy.html', 'r') as f:
    content = f.read()

target = """<button type="submit" style="background: #3b82f6;"""
replacement = """    <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; gap: 15px;">
        <input type="checkbox" id="keep_local" name="keep_local" value="1" {% if strategy.keep_local == 1 %}checked{% endif %} style="width: 20px; height: 20px; cursor: pointer;">
        <label for="keep_local" style="color: white; margin: 0; cursor: pointer;">
            <strong>Keep a Local Copy</strong><br>
            <span style="color: #94a3b8; font-size: 0.85rem;">If enabled, files are copied to external storage but the original is kept on the PBX disk. (Not recommended if you want to save space).</span>
        </label>
    </div>
    
    <button type="submit" style="background: #3b82f6;"""

if "Keep a Local Copy" not in content:
    content = content.replace(target, replacement)
    with open('/root/RCM_7021/templates/ext_storage_strategy.html', 'w') as f:
        f.write(content)

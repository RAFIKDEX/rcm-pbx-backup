with open("/root/RCM_7021/templates/cleanup_manual.html", "r") as f:
    content = f.read()

# Replace HTML part
old_html = """    <h3 style="color: white; margin-top: 30px;">2. Cleanup Criteria</h3>
    <div style="margin-bottom: 20px;">
        <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Global Rule Strategy</label>
        <select id="rule_strategy" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
            <option value="older_than_days">Older than X Days</option>
            <option value="date_range">Specific Date Range</option>
        </select>
    </div>
    
    <div style="margin-bottom: 20px;" id="div_older">
        <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Days</label>
        <input type="number" id="rule_days" value="90" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
    </div>
    
    <div style="margin-bottom: 20px; display: none;" id="div_range">
        <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Delete everything UP TO this date:</label>
        <input type="date" id="rule_date" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
    </div>"""

new_html = """    <h3 style="color: white; margin-top: 30px;">2. Cleanup Criteria</h3>
    <div style="margin-bottom: 20px;">
        <label style="color: #e2e8f0; display: block; margin-bottom: 10px;"><input type="radio" name="rule_mode" value="global" checked onclick="toggleRuleMode()"> Apply Same Rule For All Selected Categories</label>
        <label style="color: #e2e8f0; display: block; margin-bottom: 10px;"><input type="radio" name="rule_mode" value="per_category" onclick="toggleRuleMode()"> Configure Each Category Separately</label>
    </div>
    
    <div id="mode_global" style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        <div style="margin-bottom: 20px;">
            <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Global Rule Strategy</label>
            <select id="rule_strategy" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
                <option value="older_than_days">Older than X Days</option>
                <option value="date_range">Specific Date Range</option>
            </select>
        </div>
        
        <div style="margin-bottom: 20px;" id="div_older">
            <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Days</label>
            <input type="number" id="rule_days" value="90" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        
        <div style="margin-bottom: 20px; display: none;" id="div_range">
            <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Delete everything UP TO this date:</label>
            <input type="date" id="rule_date" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
    </div>

    <div id="mode_per_category" style="display: none; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px;">
            <h4 style="color: #94a3b8; margin-top:0;">CDR Records</h4>
            <label style="color: #e2e8f0; margin-right:10px;">Older than (days):</label>
            <input type="number" id="rule_days_cdr" value="180" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px;">
            <h4 style="color: #94a3b8; margin-top:0;">Call Recordings</h4>
            <label style="color: #e2e8f0; margin-right:10px;">Older than (days):</label>
            <input type="number" id="rule_days_rec" value="90" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px;">
            <h4 style="color: #94a3b8; margin-top:0;">Queue Statistics</h4>
            <label style="color: #e2e8f0; margin-right:10px;">Older than (days):</label>
            <input type="number" id="rule_days_queue" value="180" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px;">
            <h4 style="color: #94a3b8; margin-top:0;">Operation Log</h4>
            <label style="color: #e2e8f0; margin-right:10px;">Older than (days):</label>
            <input type="number" id="rule_days_oplog" value="30" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
    </div>"""
content = content.replace(old_html, new_html)

# Replace JS part
old_js = """function buildConfig() {
    let strategy = document.getElementById('rule_strategy').value;
    let value = strategy === 'older_than_days' ? document.getElementById('rule_days').value : document.getElementById('rule_date').value;
    
    let config = {};
    if(document.getElementById('chk_cdr').checked) config["CDR"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_rec').checked) config["Recordings"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_dex').checked) config["Zero_Config"] = {strategy: "older_than_days", value: 30}; // Dex fixed 30
    return config;
}"""

new_js = """function toggleRuleMode() {
    let isGlobal = document.querySelector('input[name="rule_mode"][value="global"]').checked;
    document.getElementById('mode_global').style.display = isGlobal ? 'block' : 'none';
    document.getElementById('mode_per_category').style.display = isGlobal ? 'none' : 'block';
}

function buildConfig() {
    let isGlobal = document.querySelector('input[name="rule_mode"][value="global"]').checked;
    let config = {};
    
    if (isGlobal) {
        let strategy = document.getElementById('rule_strategy').value;
        let value = strategy === 'older_than_days' ? document.getElementById('rule_days').value : document.getElementById('rule_date').value;
        if(document.getElementById('chk_cdr').checked) config["CDR"] = {strategy: strategy, value: value, to: value};
        if(document.getElementById('chk_rec').checked) config["Recordings"] = {strategy: strategy, value: value, to: value};
        if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: strategy, value: value, to: value};
        if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: strategy, value: value, to: value};
    } else {
        if(document.getElementById('chk_cdr').checked) config["CDR"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_cdr').value};
        if(document.getElementById('chk_rec').checked) config["Recordings"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_rec').value};
        if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_queue').value};
        if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_oplog').value};
    }
    
    if(document.getElementById('chk_dex').checked) config["Zero_Config"] = {strategy: "older_than_days", value: 30}; // Dex fixed 30
    return config;
}"""

content = content.replace(old_js, new_js)

with open("/root/RCM_7021/templates/cleanup_manual.html", "w") as f:
    f.write(content)

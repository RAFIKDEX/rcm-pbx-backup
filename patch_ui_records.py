# Patch manual html
with open("/root/RCM_7021/templates/cleanup_manual.html", "r") as f:
    content = f.read()

# Add option to select
content = content.replace('<option value="date_range">Specific Date Range</option>', '<option value="date_range">Specific Date Range</option>\n                <option value="keep_latest_records">Keep Latest X Records/Files</option>')

# Add input for keep_latest_records
content = content.replace('</div>\n    </div>\n\n    <div id="mode_per_category"', '</div>\n        <div style="margin-bottom: 20px; display: none;" id="div_records">\n            <label style="color: #e2e8f0; display: block; margin-bottom: 8px;">Number of Records/Files to keep:</label>\n            <input type="number" id="rule_records" value="1000" style="width: 100%; max-width: 400px; padding: 10px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">\n        </div>\n    </div>\n\n    <div id="mode_per_category"')

# JS Toggle
js_toggle_old = """    if(e.target.value === 'older_than_days') {
        document.getElementById('div_older').style.display = 'block';
        document.getElementById('div_range').style.display = 'none';
    } else {
        document.getElementById('div_older').style.display = 'none';
        document.getElementById('div_range').style.display = 'block';
    }"""
js_toggle_new = """    if(e.target.value === 'older_than_days') {
        document.getElementById('div_older').style.display = 'block';
        document.getElementById('div_range').style.display = 'none';
        document.getElementById('div_records').style.display = 'none';
    } else if(e.target.value === 'date_range') {
        document.getElementById('div_older').style.display = 'none';
        document.getElementById('div_range').style.display = 'block';
        document.getElementById('div_records').style.display = 'none';
    } else {
        document.getElementById('div_older').style.display = 'none';
        document.getElementById('div_range').style.display = 'none';
        document.getElementById('div_records').style.display = 'block';
    }"""
content = content.replace(js_toggle_old, js_toggle_new)

# JS buildConfig value mapping
js_val_old = "let value = strategy === 'older_than_days' ? document.getElementById('rule_days').value : document.getElementById('rule_date').value;"
js_val_new = "let value = strategy === 'older_than_days' ? document.getElementById('rule_days').value : (strategy === 'date_range' ? document.getElementById('rule_date').value : document.getElementById('rule_records').value);"
content = content.replace(js_val_old, js_val_new)

# Add per-category Keep Records Strategy select instead of just number
per_cat_old = """    <div id="mode_per_category" style="display: none; margin-bottom: 20px;">
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

per_cat_new = """    <div id="mode_per_category" style="display: none; margin-bottom: 20px;">
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; gap: 10px; align-items: center;">
            <h4 style="color: #94a3b8; margin:0; width: 150px;">CDR Records</h4>
            <select id="rule_strat_cdr" style="padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;"><option value="older_than_days">Older than (days)</option><option value="keep_latest_records">Keep latest (records)</option></select>
            <input type="number" id="rule_val_cdr" value="180" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; gap: 10px; align-items: center;">
            <h4 style="color: #94a3b8; margin:0; width: 150px;">Call Recordings</h4>
            <select id="rule_strat_rec" style="padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;"><option value="older_than_days">Older than (days)</option><option value="keep_latest_records">Keep latest (files)</option></select>
            <input type="number" id="rule_val_rec" value="90" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; gap: 10px; align-items: center;">
            <h4 style="color: #94a3b8; margin:0; width: 150px;">Queue Statistics</h4>
            <select id="rule_strat_queue" style="padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;"><option value="older_than_days">Older than (days)</option><option value="keep_latest_records">Keep latest (records)</option></select>
            <input type="number" id="rule_val_queue" value="180" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; gap: 10px; align-items: center;">
            <h4 style="color: #94a3b8; margin:0; width: 150px;">Operation Log</h4>
            <select id="rule_strat_oplog" style="padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;"><option value="older_than_days">Older than (days)</option><option value="keep_latest_records">Keep latest (records)</option></select>
            <input type="number" id="rule_val_oplog" value="30" style="width: 100px; padding: 8px; background: #1e293b; color: white; border: 1px solid #334155; border-radius: 6px;">
        </div>
    </div>"""
content = content.replace(per_cat_old, per_cat_new)

# Update buildConfig for per-category logic
per_cat_build_old = """    } else {
        if(document.getElementById('chk_cdr').checked) config["CDR"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_cdr').value};
        if(document.getElementById('chk_rec').checked) config["Recordings"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_rec').value};
        if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_queue').value};
        if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: 'older_than_days', value: document.getElementById('rule_days_oplog').value};
    }"""
per_cat_build_new = """    } else {
        if(document.getElementById('chk_cdr').checked) config["CDR"] = {strategy: document.getElementById('rule_strat_cdr').value, value: document.getElementById('rule_val_cdr').value};
        if(document.getElementById('chk_rec').checked) config["Recordings"] = {strategy: document.getElementById('rule_strat_rec').value, value: document.getElementById('rule_val_rec').value};
        if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: document.getElementById('rule_strat_queue').value, value: document.getElementById('rule_val_queue').value};
        if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: document.getElementById('rule_strat_oplog').value, value: document.getElementById('rule_val_oplog').value};
    }"""
content = content.replace(per_cat_build_old, per_cat_build_new)

with open("/root/RCM_7021/templates/cleanup_manual.html", "w") as f:
    f.write(content)


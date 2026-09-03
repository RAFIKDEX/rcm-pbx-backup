with open("/root/RCM_7021/templates/cleanup_manual.html", "r") as f:
    content = f.read()

checkboxes = """        <label style="display: block; color: #e2e8f0; margin-bottom: 10px;"><input type="checkbox" id="chk_queue" checked> Queue Statistics</label>
        <label style="display: block; color: #e2e8f0; margin-bottom: 10px;"><input type="checkbox" id="chk_oplog" checked> Operation Log</label>
        <label style="display: block; color: #e2e8f0; margin-bottom: 10px;"><input type="checkbox" id="chk_dex"> DEX Phones (Inactive > 30 days)</label>"""

content = content.replace('        <label style="display: block; color: #e2e8f0; margin-bottom: 10px;"><input type="checkbox" id="chk_queue" checked> Queue Statistics</label>\n        <label style="display: block; color: #e2e8f0; margin-bottom: 10px;"><input type="checkbox" id="chk_dex"> DEX Phones (Inactive > 30 days)</label>', checkboxes)

config_js = """    if(document.getElementById('chk_queue').checked) config["Queue_Stats"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_oplog').checked) config["Operation_Log"] = {strategy: strategy, value: value, to: value};
    if(document.getElementById('chk_dex').checked) config["Zero_Config"] = {strategy: "older_than_days", value: 30}; // Dex fixed 30"""

content = content.replace('    if(document.getElementById(\'chk_queue\').checked) config["Queue_Stats"] = {strategy: strategy, value: value, to: value};\n    if(document.getElementById(\'chk_dex\').checked) config["Zero_Config"] = {strategy: "older_than_days", value: 30}; // Dex fixed 30', config_js)

with open("/root/RCM_7021/templates/cleanup_manual.html", "w") as f:
    f.write(content)

import re

filepath = "/root/RCM_7021/external_storage_routes.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

target = r"""    conn = get_db\(\)
    conn\.execute\("INSERT INTO external_storage_providers \(name, provider_type, config_json\) VALUES \(\?, \?, \?\)", 
                 \(name, provider_type, json\.dumps\(config\)\)\)
    conn\.commit\(\)
    conn\.close\(\)
    flash\(f"Storage Provider '\{name\}' added successfully!", "success"\)
    return redirect\(url_for\('ext_storage_bp\.providers_list'\)\)"""

replacement = """    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO external_storage_providers (name, provider_type, config_json) VALUES (?, ?, ?)", 
                 (name, provider_type, json.dumps(config)))
    provider_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Run immediate test connection & mount
    import sys
    sys.path.append('/root/RCM_7021')
    from storage_providers import get_provider_instance
    try:
        p_instance = get_provider_instance(provider_id)
        if p_instance:
            connected = p_instance.connect()
            if connected:
                can_write = p_instance.test_write()
                if can_write:
                    flash(f"Storage Provider '{name}' added and mounted successfully!", "success")
                else:
                    flash(f"Provider '{name}' mounted but test write failed: {p_instance.last_error}", "warning")
            else:
                flash(f"Provider '{name}' saved, but failed to connect: {p_instance.last_error}", "danger")
    except Exception as e:
        flash(f"Provider saved, but error during connection test: {e}", "danger")

    return redirect(url_for('ext_storage_bp.dashboard'))"""

content = re.sub(target, replacement, content)
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

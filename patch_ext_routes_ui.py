import re

with open('/root/RCM_7021/external_storage_routes.py', 'r') as f:
    content = f.read()

new_routes = """
@ext_storage_bp.route('/providers/add', methods=['POST'])
@require_admin
def add_provider():
    provider_type = request.form.get('provider_type')
    name = request.form.get('name')
    
    config = {}
    if provider_type == 'nas':
        config['protocol'] = request.form.get('protocol', 'smb')
        config['server'] = request.form.get('server')
        config['share'] = request.form.get('share')
        config['username'] = request.form.get('username', '')
        config['password'] = request.form.get('password', '')
        config['base_folder'] = request.form.get('base_folder', 'RCM')
    elif provider_type == 'google_drive':
        config['credentials_json'] = request.form.get('credentials_json', '')
        config['folder_id'] = request.form.get('folder_id', 'root')
    elif provider_type == 'usb':
        config['device_path'] = request.form.get('device_path')
        config['base_folder'] = request.form.get('base_folder', 'RCM')
        
    conn = get_db()
    conn.execute("INSERT INTO external_storage_providers (name, provider_type, config_json) VALUES (?, ?, ?)", 
                 (name, provider_type, json.dumps(config)))
    conn.commit()
    conn.close()
    flash(f"Storage Provider '{name}' added successfully!", "success")
    return redirect(url_for('ext_storage_bp.providers_list'))

@ext_storage_bp.route('/providers/delete/<int:id>', methods=['POST'])
@require_admin
def delete_provider(id):
    conn = get_db()
    conn.execute("DELETE FROM external_storage_providers WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Storage Provider deleted.", "info")
    return redirect(url_for('ext_storage_bp.providers_list'))

@ext_storage_bp.route('/policies/add', methods=['POST'])
@require_admin
def add_policy():
    name = request.form.get('name')
    provider_id = request.form.get('provider_id')
    age_days = request.form.get('age_days', 30)
    action_mode = request.form.get('action_mode', 'move_delete')
    
    conn = get_db()
    conn.execute("INSERT INTO storage_policies (name, provider_id, age_days, action_mode) VALUES (?, ?, ?, ?)",
                 (name, provider_id, age_days, action_mode))
    conn.commit()
    conn.close()
    flash(f"Policy '{name}' activated successfully!", "success")
    return redirect(url_for('ext_storage_bp.policies_list'))

@ext_storage_bp.route('/policies/delete/<int:id>', methods=['POST'])
@require_admin
def delete_policy(id):
    conn = get_db()
    conn.execute("DELETE FROM storage_policies WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Policy deleted.", "info")
    return redirect(url_for('ext_storage_bp.policies_list'))
"""

if "def add_provider():" not in content:
    content += new_routes
    with open('/root/RCM_7021/external_storage_routes.py', 'w') as f:
        f.write(content)

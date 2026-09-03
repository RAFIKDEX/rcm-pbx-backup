import re

with open('/root/RCM_7021/external_storage_routes.py', 'r') as f:
    content = f.read()

new_routes = """
@ext_storage_bp.route('/strategy', methods=['GET', 'POST'])
@require_admin
def storage_strategy():
    conn = get_db()
    if request.method == 'POST':
        mode = request.form.get('mode')
        static_provider_id = request.form.get('static_provider_id') or None
        dynamic_order = request.form.getlist('dynamic_order[]')
        
        conn.execute("UPDATE storage_strategy SET mode=?, static_provider_id=?, dynamic_order_json=? WHERE id=1",
                     (mode, static_provider_id, json.dumps(dynamic_order)))
        conn.commit()
        flash("Storage Strategy updated successfully. It will apply immediately to new calls.", "success")
        return redirect(url_for('ext_storage_bp.storage_strategy'))
        
    strategy = conn.execute("SELECT * FROM storage_strategy WHERE id=1").fetchone()
    providers = conn.execute("SELECT id, name, provider_type FROM external_storage_providers").fetchall()
    conn.close()
    
    dynamic_order = json.loads(strategy['dynamic_order_json']) if strategy['dynamic_order_json'] else []
    
    return render_template('ext_storage_strategy.html', strategy=strategy, providers=providers, dynamic_order=dynamic_order)
"""

if "def storage_strategy():" not in content:
    content += new_routes
    with open('/root/RCM_7021/external_storage_routes.py', 'w') as f:
        f.write(content)

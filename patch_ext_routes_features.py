import re

with open('/root/RCM_7021/external_storage_routes.py', 'r') as f:
    content = f.read()

new_routes = """
@ext_storage_bp.route('/providers/test/<int:id>', methods=['POST'])
@require_admin
def test_provider(id):
    import sys
    sys.path.append('/root/RCM_7021')
    from storage_providers import get_provider_instance
    provider = get_provider_instance(id)
    if not provider:
        flash("Provider not found.", "danger")
        return redirect(url_for('ext_storage_bp.providers_list'))
        
    if provider.test_write():
        flash("Connection and write test SUCCESSFUL!", "success")
    else:
        flash(f"Connection FAILED: {provider.last_error}", "danger")
        
    return redirect(url_for('ext_storage_bp.providers_list'))

@ext_storage_bp.route('/policies/run_now', methods=['POST'])
@require_admin
def run_policies_now():
    import sys
    sys.path.append('/root/RCM_7021')
    try:
        from export_worker import ExportWorker
        worker = ExportWorker()
        worker.execute_scheduled_policies()
        worker.close()
        flash("Background worker executed successfully.", "success")
    except Exception as e:
        flash(f"Error executing worker: {e}", "danger")
    return redirect(url_for('ext_storage_bp.policies_list'))
"""

if "def test_provider(id):" not in content:
    content += new_routes
    with open('/root/RCM_7021/external_storage_routes.py', 'w') as f:
        f.write(content)

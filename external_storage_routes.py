from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session
import sqlite3
import json
import os
import shutil
import subprocess
from functools import wraps

ext_storage_bp = Blueprint('ext_storage_bp', __name__, url_prefix='/external-storage')

MAIN_DB = "/root/RCM_7021/rcm_7021.db"

def get_db():
    conn = sqlite3.connect(MAIN_DB)
    conn.row_factory = sqlite3.Row
    return conn

# Dummy permission check for simplicity in standalone blueprint
def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Unauthorized access.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@ext_storage_bp.route('/')
@require_admin
def dashboard():
    conn = get_db()
    
    # 1. Get Strategy
    strategy = conn.execute("SELECT * FROM storage_strategy WHERE id=1").fetchone()
    
    # 2. Get Overall Stats
    stats = conn.execute("""
        SELECT 
            COUNT(id) as total_files,
            SUM(file_size) as total_bytes 
        FROM recording_locations 
        WHERE provider_id IS NOT NULL AND transfer_status = 'Success'
    """).fetchone()
    
    total_files = stats['total_files'] or 0
    total_bytes = stats['total_bytes'] or 0
    saved_gb = round(total_bytes / (1024 * 1024 * 1024), 2)
    saved_mb = round(total_bytes / (1024 * 1024), 2)
    saved_display = f"{saved_gb} GB" if saved_gb >= 1 else f"{saved_mb} MB"
    
    # 3. Get Providers Info
    providers_rows = conn.execute("SELECT * FROM external_storage_providers").fetchall()
    providers = []
    import os
    for row in providers_rows:
        p_dict = dict(row)
        mount_point = f"/mnt/rcm_external_storage/provider_{p_dict['id']}"
        is_mounted = os.path.ismount(mount_point)
        p_dict['is_mounted'] = is_mounted
        
        # Calculate real disk usage if mounted
        if is_mounted:
            try:
                total, used, free = shutil.disk_usage(mount_point)
                p_dict['capacity_bytes'] = total
                p_dict['used_bytes'] = used
            except Exception:
                pass
                
        providers.append(p_dict)
    
    # 4. Get Recent Transfers
    recent_transfers = conn.execute("""
        SELECT r.*, p.name as provider_name 
        FROM recording_locations r
        LEFT JOIN external_storage_providers p ON r.provider_id = p.id
        WHERE r.provider_id IS NOT NULL 
        ORDER BY r.transferred_at DESC LIMIT 6
    """).fetchall()

    # 5. Get Chart Data (Last 7 Days)
    chart_data_rows = conn.execute("""
        SELECT date(transferred_at) as tdate, COUNT(id) as cnt, SUM(file_size) as bytes
        FROM recording_locations
        WHERE provider_id IS NOT NULL AND transfer_status = 'Success'
          AND transferred_at >= date('now', '-7 days')
        GROUP BY date(transferred_at)
        ORDER BY tdate ASC
    """).fetchall()
    
    import datetime
    labels = []
    data_counts = []
    data_bytes = []
    
    today = datetime.date.today()
    date_dict = { (today - datetime.timedelta(days=i)).strftime('%Y-%m-%d'): {'cnt':0, 'bytes':0} for i in range(6, -1, -1) }
    
    for r in chart_data_rows:
        if r['tdate'] in date_dict:
            date_dict[r['tdate']]['cnt'] = r['cnt']
            date_dict[r['tdate']]['bytes'] = round(r['bytes'] / (1024 * 1024), 2) # MB
            
    for k in sorted(date_dict.keys()):
        labels.append(k)
        data_counts.append(date_dict[k]['cnt'])
        data_bytes.append(date_dict[k]['bytes'])

    conn.close()
    
    total_disk, used_disk, free_disk = shutil.disk_usage("/")
    free_gb = round(free_disk / (1024 * 1024 * 1024), 2)
    total_gb = round(total_disk / (1024 * 1024 * 1024), 2)
    
    return render_template(
        'ext_storage_dashboard.html', 
        strategy=strategy,
        total_files=total_files,
        saved_display=saved_display,
        providers=providers,
        recent_transfers=recent_transfers,
        chart_labels=labels,
        chart_counts=data_counts,
        chart_bytes=data_bytes,
        free_space=f"{free_gb} GB",
        total_space=f"{total_gb} GB"
    )

@ext_storage_bp.route('/providers')
@require_admin
def providers_list():
    conn = get_db()
    providers = conn.execute("SELECT * FROM external_storage_providers").fetchall()
    conn.close()
    return render_template('ext_storage_providers.html', providers=providers)

@ext_storage_bp.route('/policies')
@require_admin
def policies_list():
    conn = get_db()
    policies = conn.execute("""
        SELECT p.*, pr.name as provider_name 
        FROM storage_policies p
        JOIN external_storage_providers pr ON p.provider_id = pr.id
    """).fetchall()
    providers = conn.execute("SELECT id, name FROM external_storage_providers WHERE enabled=1").fetchall()
    conn.close()
    return render_template('ext_storage_policies.html', policies=policies, providers=providers)

@ext_storage_bp.route('/reports', methods=['GET', 'POST'])
@require_admin
def reports_dashboard():
    if request.method == 'POST':
        # Trigger manual report
        report_type = request.form.get('report_type')
        date_from = request.form.get('date_from')
        date_to = request.form.get('date_to')
        target_ext = request.form.get('target_ext') # Agent or Queue
        provider_id = request.form.get('provider_id')
        
        try:
            from report_generator import ReportGenerator
            gen = ReportGenerator(provider_id=provider_id)
            filepath = None
            if report_type == 'single_agent':
                filepath = gen.generate_single_agent(target_ext, date_from, date_to)
            elif report_type == 'single_queue':
                filepath = gen.generate_single_queue(target_ext, date_from, date_to)
            elif report_type == 'all_agents':
                filepath = gen.generate_all_agents(date_from, date_to)
            elif report_type == 'all_queues':
                filepath = gen.generate_all_queues(date_from, date_to)
            
            if filepath and provider_id:
                gen.archive_report(filepath, report_type, "Manual", date_from, date_to)
                flash(f"Report {report_type} generated and archived successfully.", "success")
            elif filepath:
                # Need to download immediately if no provider
                from flask import send_file
                return send_file(filepath, as_attachment=True)
        except Exception as e:
            flash(f"Error generating report: {e}", "danger")
            
        return redirect(url_for('ext_storage_bp.reports_dashboard'))
        
    conn = get_db()
    reports = conn.execute("SELECT * FROM reports_archive ORDER BY generated_at DESC LIMIT 20").fetchall()
    providers = conn.execute("SELECT id, name FROM external_storage_providers WHERE enabled=1").fetchall()
    conn.close()
    return render_template('ext_storage_reports.html', reports=reports, providers=providers)



@ext_storage_bp.route('/providers/add', methods=['POST'])
@require_admin
def add_provider():
    provider_type = request.form.get('provider_type')
    name = request.form.get('name')
    
    config = {}
    import sys
    sys.path.append('/root/RCM_7021')
    import crypto_helper
    
    if provider_type == 'nas':
        config['protocol'] = request.form.get('protocol', 'smb')
        config['server'] = request.form.get('server')
        config['share'] = request.form.get('share')
        config['username'] = request.form.get('username', '')
        
        raw_password = request.form.get('password', '')
        config['password'] = crypto_helper.encrypt_secret(raw_password)
        
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
    return redirect(url_for('ext_storage_bp.dashboard'))

@ext_storage_bp.route('/providers/delete/<int:id>', methods=['POST'])
@require_admin
def delete_provider(id):
    conn = get_db()
    conn.execute("DELETE FROM external_storage_providers WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Storage Provider deleted.", "info")
    return redirect(url_for('ext_storage_bp.dashboard'))

@ext_storage_bp.route('/providers/edit/<int:id>', methods=['GET', 'POST'])
@require_admin
def edit_provider(id):
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name')
        protocol = request.form.get('protocol')
        server = request.form.get('server')
        share = request.form.get('share')
        base_folder = request.form.get('base_folder')
        username = request.form.get('username')
        new_password = request.form.get('password')
        
        provider = conn.execute("SELECT * FROM external_storage_providers WHERE id=?", (id,)).fetchone()
        if not provider:
            return redirect(url_for('ext_storage_bp.dashboard'))
            
        config = json.loads(provider['config_json'])
        config['protocol'] = protocol
        config['server'] = server
        config['share'] = share
        config['base_folder'] = base_folder
        config['username'] = username
        
        import sys
        if '/root/RCM_7021' not in sys.path:
            sys.path.append('/root/RCM_7021')
        import crypto_helper
        
        if new_password:
            config['password'] = crypto_helper.encrypt_secret(new_password)
            
        conn.execute("UPDATE external_storage_providers SET name=?, config_json=? WHERE id=?", (name, json.dumps(config), id))
        conn.commit()
        conn.close()
        flash("Provider updated successfully.", "success")
        return redirect(url_for('ext_storage_bp.dashboard'))
        
    provider = conn.execute("SELECT * FROM external_storage_providers WHERE id=?", (id,)).fetchone()
    conn.close()
    if not provider:
        return redirect(url_for('ext_storage_bp.dashboard'))
        
    config = json.loads(provider['config_json'])
    return render_template('ext_storage_provider_edit.html', provider=provider, config=config)

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

@ext_storage_bp.route('/providers/test/<int:id>', methods=['POST'])
@require_admin
def test_provider(id):
    import sys
    sys.path.append('/root/RCM_7021')
    from storage_providers import get_provider_instance
    provider = get_provider_instance(id)
    if not provider:
        flash("Provider not found.", "danger")
        return redirect(url_for('ext_storage_bp.dashboard'))
        
    if provider.test_write():
        flash("Connection and write test SUCCESSFUL!", "success")
    else:
        flash(f"Connection FAILED: {provider.last_error}", "danger")
        
    return redirect(url_for('ext_storage_bp.dashboard'))

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

@ext_storage_bp.route('/strategy', methods=['GET', 'POST'])
@require_admin
def storage_strategy():
    conn = get_db()
    if request.method == 'POST':
        mode = request.form.get('mode')
        static_provider_id = request.form.get('static_provider_id') or None
        dynamic_order = request.form.getlist('dynamic_order[]')
        keep_local = 1 if request.form.get('keep_local') else 0
        
        conn.execute("UPDATE storage_strategy SET mode=?, static_provider_id=?, dynamic_order_json=?, keep_local=? WHERE id=1",
                     (mode, static_provider_id, json.dumps(dynamic_order), keep_local))
        conn.commit()
        flash("Storage Strategy updated successfully. It will apply immediately to new calls.", "success")
        return redirect(url_for('ext_storage_bp.storage_strategy'))
        
    strategy = conn.execute("SELECT * FROM storage_strategy WHERE id=1").fetchone()
    providers = conn.execute("SELECT id, name, provider_type FROM external_storage_providers").fetchall()
    conn.close()
    
    dynamic_order = json.loads(strategy['dynamic_order_json']) if strategy['dynamic_order_json'] else []
    
    return render_template('ext_storage_strategy.html', strategy=strategy, providers=providers, dynamic_order=dynamic_order)

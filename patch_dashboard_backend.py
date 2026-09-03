import re

filepath = "/root/RCM_7021/external_storage_routes.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the dashboard route
old_route = r"""@ext_storage_bp\.route\('/'\)
@require_admin
def dashboard\(\):
    conn = get_db\(\)
    providers = conn\.execute\("SELECT \* FROM external_storage_providers"\)\.fetchall\(\)
    jobs = conn\.execute\("SELECT \* FROM export_jobs ORDER BY start_time DESC LIMIT 5"\)\.fetchall\(\)
    conn\.close\(\)
    return render_template\('ext_storage_dashboard\.html', providers=providers, jobs=jobs\)"""

new_route = """@ext_storage_bp.route('/')
@require_admin
def dashboard():
    conn = get_db()
    
    # 1. Get Strategy
    strategy = conn.execute("SELECT * FROM storage_strategy WHERE id=1").fetchone()
    
    # 2. Get Overall Stats
    stats = conn.execute(\"\"\"
        SELECT 
            COUNT(id) as total_files,
            SUM(file_size) as total_bytes 
        FROM recording_locations 
        WHERE provider_id IS NOT NULL AND transfer_status = 'Success'
    \"\"\").fetchone()
    
    total_files = stats['total_files'] or 0
    total_bytes = stats['total_bytes'] or 0
    saved_gb = round(total_bytes / (1024 * 1024 * 1024), 2)
    saved_mb = round(total_bytes / (1024 * 1024), 2)
    saved_display = f"{saved_gb} GB" if saved_gb >= 1 else f"{saved_mb} MB"
    
    # 3. Get Providers Info
    providers = conn.execute("SELECT * FROM external_storage_providers").fetchall()
    
    # 4. Get Recent Transfers
    recent_transfers = conn.execute(\"\"\"
        SELECT r.*, p.name as provider_name 
        FROM recording_locations r
        LEFT JOIN external_storage_providers p ON r.provider_id = p.id
        WHERE r.provider_id IS NOT NULL 
        ORDER BY r.transferred_at DESC LIMIT 6
    \"\"\").fetchall()

    # 5. Get Chart Data (Last 7 Days)
    chart_data_rows = conn.execute(\"\"\"
        SELECT date(transferred_at) as tdate, COUNT(id) as cnt, SUM(file_size) as bytes
        FROM recording_locations
        WHERE provider_id IS NOT NULL AND transfer_status = 'Success'
          AND transferred_at >= date('now', '-7 days')
        GROUP BY date(transferred_at)
        ORDER BY tdate ASC
    \"\"\").fetchall()
    
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
    
    return render_template(
        'ext_storage_dashboard.html', 
        strategy=strategy,
        total_files=total_files,
        saved_display=saved_display,
        providers=providers,
        recent_transfers=recent_transfers,
        chart_labels=labels,
        chart_counts=data_counts,
        chart_bytes=data_bytes
    )"""

content = re.sub(old_route, new_route, content)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

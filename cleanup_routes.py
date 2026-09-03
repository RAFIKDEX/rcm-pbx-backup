import json
import os
import shutil
import sqlite3
from flask import Blueprint, render_template, request, jsonify, session, current_app, redirect, url_for
from app import require_permission
import db

cleanup_bp = Blueprint('cleanup_bp', __name__, url_prefix='/cleanup')

def get_storage_info():
    total, used, free = shutil.disk_usage("/")
    return {
        "total": total,
        "used": used,
        "free": free,
        "usage_percent": round((used / total) * 100, 2) if total else 0
    }

@cleanup_bp.route('/')
def cleanup_dashboard():
    # Only Admin or specific role
    if session.get("role") != "admin":
        return "Unauthorized", 403
    storage = get_storage_info()
    return render_template('cleanup_dashboard.html', storage=storage)

@cleanup_bp.route('/manual', methods=['GET'])
def manual_cleanup_form():
    if session.get("role") != "admin":
        return "Unauthorized", 403
    return render_template('cleanup_manual.html')

@cleanup_bp.route('/manual/analyze', methods=['POST'])
def start_analyze():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    config = request.json
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO cleanup_jobs (job_type, status, progress_percent, cancel_requested)
        VALUES ('Manual_Analyze', 'Pending', 0, 0)
    ''')
    job_id = cursor.lastrowid
    conn.commit()
    
    # Spawn background thread to analyze
    import threading
    from cleanup_engine import CleanupEngine
    
    def run_analyze(jid, cfg):
        engine = CleanupEngine(jid, cfg)
        engine.scan_and_analyze()
        
    t = threading.Thread(target=run_analyze, args=(job_id, config), daemon=True)
    t.start()
    
    return jsonify({"job_id": job_id})

@cleanup_bp.route('/manual/execute/<int:job_id>', methods=['POST'])
def execute_cleanup(job_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
        
    config = request.json
    conn = db.get_db()
    cursor = conn.cursor()
    # Update job to Cleanup phase
    cursor.execute('''
        UPDATE cleanup_jobs SET job_type='Manual_Cleanup', status='Pending', progress_percent=0, progress_details='', cancel_requested=0
        WHERE id=?
    ''', (job_id,))
    conn.commit()
    
    import threading
    from cleanup_engine import CleanupEngine
    
    def run_execute(jid, cfg):
        engine = CleanupEngine(jid, cfg)
        engine.execute_cleanup()
        
    t = threading.Thread(target=run_execute, args=(job_id, config), daemon=True)
    t.start()
    
    return jsonify({"status": "started", "job_id": job_id})

@cleanup_bp.route('/job/<int:job_id>', methods=['GET'])
def job_status(job_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT status, progress_percent, progress_details, cancel_requested FROM cleanup_jobs WHERE id=?', (job_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": "Job not found"}), 404
        
    details = {}
    if row['progress_details']:
        try:
            details = json.loads(row['progress_details'])
        except:
            pass
            
    return jsonify({
        "status": row['status'],
        "progress_percent": row['progress_percent'],
        "details": details,
        "cancel_requested": row['cancel_requested']
    })

@cleanup_bp.route('/job/<int:job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
        
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE cleanup_jobs SET cancel_requested=1 WHERE id=?', (job_id,))
    conn.commit()
    return jsonify({"status": "cancellation_requested"})

@cleanup_bp.route('/history', methods=['GET'])
def history():
    if session.get("role") != "admin":
        return "Unauthorized", 403
        
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
        
    per_page = 10
    offset = (page - 1) * per_page
        
    conn = db.get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as cnt FROM cleanup_history')
    row = cursor.fetchone()
    total_records = row['cnt'] if row else 0
    total_pages = max(1, (total_records + per_page - 1) // per_page)
    
    cursor.execute('SELECT * FROM cleanup_history ORDER BY id DESC LIMIT ? OFFSET ?', (per_page, offset))
    records = cursor.fetchall()
    
    return render_template('cleanup_history.html', records=records, page=page, total_pages=total_pages)

@cleanup_bp.route('/auto', methods=['GET', 'POST'])
def auto_config():
    if session.get("role") != "admin":
        return "Unauthorized", 403
        
    conn = db.get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        enabled = data.get('enabled', 0)
        rules_json = json.dumps(data.get('rules', {}))
        schedule_time = data.get('schedule_time', '03:00')
        schedule_type = data.get('schedule_type', 'daily')
        
        disk_trigger_enabled = data.get('disk_trigger_enabled', 0)
        disk_trigger_percent = data.get('disk_trigger_percent', 90)
        disk_target_percent = data.get('disk_target_percent', 75)
        
        cursor.execute('''
            UPDATE cleanup_auto_config 
            SET enabled=?, rules_json=?, schedule_time=?, schedule_type=?,
                disk_trigger_enabled=?, disk_trigger_percent=?, disk_target_percent=?
            WHERE id=1
        ''', (enabled, rules_json, schedule_time, schedule_type, disk_trigger_enabled, disk_trigger_percent, disk_target_percent))
        conn.commit()
        return jsonify({"status": "success"})
        
    cursor.execute('SELECT * FROM cleanup_auto_config WHERE id=1')
    row = cursor.fetchone()
    if not row:
        row = {'enabled': 0, 'schedule_type': 'daily', 'schedule_time': '03:00', 'rules_json': '{}', 'disk_trigger_enabled': 0, 'disk_trigger_percent': 90, 'disk_target_percent': 75}
    return render_template('cleanup_auto.html', config=row)


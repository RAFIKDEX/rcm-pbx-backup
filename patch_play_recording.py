import re

with open('/root/RCM_7021/app.py', 'r') as f:
    content = f.read()

target = """@app.route('/recordings/play/<filename>')
@require_reporting_scope('call_records')
def play_recording(filename):
    if not _recording_scope_allows_filename('call_records', filename):
        return "Access Denied", 403
    return send_from_directory("/var/spool/asterisk/monitor", filename)"""

replacement = """@app.route('/recordings/play/<filename>')
@require_reporting_scope('call_records')
def play_recording(filename):
    if not _recording_scope_allows_filename('call_records', filename):
        return "Access Denied", 403
        
    # Check recording_locations first
    import sqlite3
    try:
        conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM recording_locations WHERE local_path LIKE ? OR cdr_uniqueid=?", (f"%{filename}", filename))
        loc = c.fetchone()
        conn.close()
        
        if loc and loc['provider_id']:
            # Stream from external provider
            import sys
            sys.path.append('/root/RCM_7021')
            from storage_providers import get_provider_instance
            provider = get_provider_instance(loc['provider_id'])
            
            # If NAS/USB, it's a mounted path
            if provider.__class__.__name__ in ['NASStorageProvider', 'USBStorageProvider']:
                ext_path = loc['external_path']
                full_path = os.path.join(provider.mount_point, provider.base_folder, ext_path)
                if os.path.exists(full_path):
                    from flask import send_file
                    return send_file(full_path, mimetype='audio/wav')
    except Exception as e:
        print(f"External recording playback error: {e}")

    # Fallback to local
    return send_from_directory("/var/spool/asterisk/monitor", filename)"""

content = content.replace(target, replacement)

# Do the same for extension_portal_recording_file
target2 = """@app.route('/portal/recordings/file/<filename>')
@require_portal_session
def extension_portal_recording_file(filename):
    ext = session.get('portal_extension')
    owned = _recording_owned_by(filename, ext)
    if not owned:
        return "Access Denied", 403
    return send_from_directory("/var/spool/asterisk/monitor", filename)"""

replacement2 = """@app.route('/portal/recordings/file/<filename>')
@require_portal_session
def extension_portal_recording_file(filename):
    ext = session.get('portal_extension')
    owned = _recording_owned_by(filename, ext)
    if not owned:
        return "Access Denied", 403
        
    import sqlite3
    try:
        conn = sqlite3.connect("/root/RCM_7021/rcm_7021.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM recording_locations WHERE local_path LIKE ? OR cdr_uniqueid=?", (f"%{filename}", filename))
        loc = c.fetchone()
        conn.close()
        if loc and loc['provider_id']:
            import sys
            sys.path.append('/root/RCM_7021')
            from storage_providers import get_provider_instance
            provider = get_provider_instance(loc['provider_id'])
            if provider.__class__.__name__ in ['NASStorageProvider', 'USBStorageProvider']:
                ext_path = loc['external_path']
                full_path = os.path.join(provider.mount_point, provider.base_folder, ext_path)
                if os.path.exists(full_path):
                    from flask import send_file
                    return send_file(full_path, as_attachment=True, download_name=filename)
    except Exception as e:
        pass
        
    return send_from_directory("/var/spool/asterisk/monitor", filename)"""

content = content.replace(target2, replacement2)

with open('/root/RCM_7021/app.py', 'w') as f:
    f.write(content)

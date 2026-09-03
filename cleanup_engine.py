import os
import glob
import sqlite3
import json
import time
import logging
from datetime import datetime, timedelta

class CleanupEngine:
    def __init__(self, job_id, config):
        self.job_id = job_id
        self.config = config
        self.main_db = '/root/RCM_7021/rcm_7021.db'
        self.queue_db = '/root/RCM_7021/rcm_queue.db'
        self.op_log = '/etc/asterisk/rcm_pbx_operation_log.json'
        self.recordings_dir = '/var/spool/asterisk/monitor/'
        self.voicemail_dir = '/var/spool/asterisk/voicemail/default/'
        self.coredumps_dir = '/var/log/asterisk/' # typically where coredumps go, or /tmp
        self.zero_config_dir = '/tftpboot/'
        self.troubleshooting_dir = '/var/log/asterisk/troubleshooting/'

        self.protected_paths = [
            '/var/lib/asterisk/sounds',
            '/var/lib/asterisk/moh'
        ]

    def _is_protected(self, path):
        for p in self.protected_paths:
            if path.startswith(p):
                return True
        return False

    def _is_cancel_requested(self):
        try:
            with sqlite3.connect(self.main_db) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cancel_requested FROM cleanup_jobs WHERE id = ?", (self.job_id,))
                row = cursor.fetchone()
                if row and row[0] == 1:
                    return True
        except Exception as e:
            logging.error(f"Error checking cancel status: {e}")
        return False

    def _update_progress(self, progress, status='Running', details=None):
        try:
            import json
            with sqlite3.connect(self.main_db) as conn:
                cursor = conn.cursor()
                if details is not None:
                    cursor.execute("UPDATE cleanup_jobs SET progress_percent = ?, status = ?, progress_details = ? WHERE id = ?", (progress, status, json.dumps(details), self.job_id))
                else:
                    cursor.execute("UPDATE cleanup_jobs SET progress_percent = ?, status = ? WHERE id = ?", (progress, status, self.job_id))
                conn.commit()
        except Exception as e:
            import logging
            logging.error(f"Error updating progress: {e}")


    def _get_threshold(self, cat_cfg):
        strategy = cat_cfg.get("strategy")
        if strategy == "older_than_days":
            val = int(cat_cfg.get("value", 30))
            return datetime.now() - timedelta(days=val)
        elif strategy == "date_range":
            to_date = cat_cfg.get("to")
            if to_date:
                return datetime.fromisoformat(to_date)
        return datetime.now() - timedelta(days=30) # default fallback

    def _scan_files(self, directories, threshold_date):
        if isinstance(directories, str):
            directories = [directories]
            
        stats = {'count': 0, 'size': 0, 'oldest': None, 'newest': None}
        threshold_ts = threshold_date.timestamp()
        
        for directory in directories:
            if not os.path.exists(directory):
                continue

        for root, _, files in os.walk(directory):
            if self._is_protected(root):
                continue
            for f in files:
                filepath = os.path.join(root, f)
                if self._is_protected(filepath):
                    continue
                try:
                    stat = os.stat(filepath)
                    mtime = stat.st_mtime
                    if mtime < threshold_ts:
                        stats['count'] += 1
                        stats['size'] += stat.st_size
                        if stats['oldest'] is None or mtime < stats['oldest']:
                            stats['oldest'] = mtime
                        if stats['newest'] is None or mtime > stats['newest']:
                            stats['newest'] = mtime
                except OSError:
                    pass
        return stats
        
    def _scan_db(self, db_path, table, date_column, threshold_date):
        stats = {'count': 0, 'size': 0, 'oldest': None, 'newest': None}
        if not os.path.exists(db_path):
            return stats
            
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*), MIN({date_column}), MAX({date_column}) FROM {table} WHERE {date_column} < ?", (threshold_date.isoformat(),))
                row = cursor.fetchone()
                if row:
                    stats['count'] = row[0] or 0
                    stats['oldest'] = row[1]
                    stats['newest'] = row[2]
        except Exception as e:
            logging.error(f"Error scanning DB {db_path} table {table}: {e}")
        return stats

    def scan_and_analyze(self):
        stats = {}
        for category, cat_cfg in self.config.items():
            if not cat_cfg.get("enabled"):
                continue
                
            threshold = self._get_threshold(cat_cfg)
            
            cat_stats = {'count': 0, 'size': 0, 'oldest': None, 'newest': None}
            if category == 'Recordings':
                dirs = [self.recordings_dir]
                if cat_cfg.get('include_external'):
                    import sqlite3
                    try:
                        with sqlite3.connect(self.main_db) as conn:
                            cur = conn.cursor()
                            rows = cur.execute("SELECT id FROM external_storage_providers WHERE enabled=1").fetchall()
                            for r in rows:
                                dirs.append(f"/mnt/rcm_external_storage/provider_{r[0]}")
                    except Exception as e:
                        pass
                cat_stats = self._scan_files(dirs, threshold)
            elif category == 'Voicemail':
                cat_stats = self._scan_files(self.voicemail_dir, threshold)
            elif category == 'Coredumps':
                cat_stats = self._scan_files(self.coredumps_dir, threshold)
            elif category == 'Zero Config Files':
                cat_stats = self._scan_files(self.zero_config_dir, threshold)
            elif category == 'Troubleshooting':
                cat_stats = self._scan_files(self.troubleshooting_dir, threshold)
            elif category == 'CDR':
                cat_stats = self._scan_db(self.main_db, 'cdr_records', 'start_time', threshold)
            elif category == 'Queue Statistics Reports':
                cat_stats = self._scan_db(self.queue_db, 'queue_calls', 'entry_time', threshold)
            elif category == 'Operation Log':
                pass # JSON processing could be slow, skip detailed scan stats for now
            
            stats[category] = cat_stats
            
        self._update_progress(100, 'Completed', {'stats': stats})
        return stats

    def _delete_files_batch(self, directories, threshold_date):
        if isinstance(directories, str):
            directories = [directories]
            
        deleted_count = 0
        space_freed = 0
        threshold_ts = threshold_date.timestamp()

        for directory in directories:
            if not os.path.exists(directory):
                continue

        for root, _, files in os.walk(directory):
            if self._is_protected(root):
                continue
            for i, f in enumerate(files):
                if self._is_cancel_requested():
                    return deleted_count, space_freed
                    
                filepath = os.path.join(root, f)
                if self._is_protected(filepath):
                    continue
                try:
                    stat = os.stat(filepath)
                    if stat.st_mtime < threshold_ts:
                        size = stat.st_size
                        os.remove(filepath)
                        deleted_count += 1
                        space_freed += size
                except OSError:
                    pass
                
                # Periodically update progress if needed or at least yield
                if i % 100 == 0:
                    time.sleep(0.01)

        return deleted_count, space_freed

    def _delete_db_batch(self, db_path, table, date_column, threshold_date, id_column='id'):
        deleted_count = 0
        if not os.path.exists(db_path):
            return 0

        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                while True:
                    if self._is_cancel_requested():
                        break
                        
                    # Delete in batches of 500
                    cursor.execute(f"""
                        DELETE FROM {table} 
                        WHERE {id_column} IN (
                            SELECT {id_column} FROM {table} 
                            WHERE {date_column} < ? 
                            LIMIT 500
                        )
                    """, (threshold_date.isoformat(),))
                    
                    rows_deleted = cursor.rowcount
                    if rows_deleted == 0:
                        break
                        
                    deleted_count += rows_deleted
                    conn.commit()
                    time.sleep(0.05) # Prevent long locks
                    
        except Exception as e:
            logging.error(f"Error cleaning DB {db_path} table {table}: {e}")
            
        return deleted_count

    def execute_cleanup(self):
        self.stats = {}
        self.total_freed = 0
        
        active_cats = [c for c, cfg in self.config.items() if cfg.get('enabled')]
        if not active_cats:
            self._update_progress(100, 'Completed')
            return

        total = len(active_cats)
        
        for idx, category in enumerate(active_cats):
            if self._is_cancel_requested():
                self._update_progress(100, 'Cancelled')
                return
                
            cat_cfg = self.config[category]
            threshold = self._get_threshold(cat_cfg)
            
            deleted = 0
            freed = 0
            status = 'Completed'
            
            try:
                if category == 'Recordings':
                    dirs = [self.recordings_dir]
                    if cat_cfg.get('include_external'):
                        import sqlite3
                        try:
                            with sqlite3.connect(self.main_db) as conn:
                                cur = conn.cursor()
                                rows = cur.execute("SELECT id FROM external_storage_providers WHERE enabled=1").fetchall()
                                for r in rows:
                                    dirs.append(f"/mnt/rcm_external_storage/provider_{r[0]}")
                        except Exception as e:
                            pass
                    deleted, freed = self._delete_files_batch(dirs, threshold)
                elif category == 'Voicemail':
                    deleted, freed = self._delete_files_batch(self.voicemail_dir, threshold)
                elif category == 'Coredumps':
                    deleted, freed = self._delete_files_batch(self.coredumps_dir, threshold)
                elif category == 'Zero Config Files':
                    deleted, freed = self._delete_files_batch(self.zero_config_dir, threshold)
                elif category == 'Troubleshooting':
                    deleted, freed = self._delete_files_batch(self.troubleshooting_dir, threshold)
                elif category == 'CDR':
                    deleted = self._delete_db_batch(self.main_db, 'cdr_records', 'start_time', threshold, 'uniqueid')
                    freed = 0
                elif category == 'Queue Statistics Reports':
                    deleted = self._delete_db_batch(self.queue_db, 'queue_calls', 'entry_time', threshold, 'call_id')
                    freed = 0
                elif category == 'DEX Phones':
                    deleted = self._delete_db_batch(self.main_db, 'dex_devices', 'last_seen', threshold, 'id')
                    freed = 0
                elif category == 'Operation Log':
                    pass # Custom logic for JSON needed
            except Exception as e:
                logging.error(f"Failed cleaning {category}: {e}")
                status = 'Failed'
                
            self.stats[category] = {"count": deleted, "size": freed}
            self.total_freed += freed
            
            prog = int(((idx + 1) / total) * 100)
            self._update_progress(prog, 'Running')


        # --- Email Alert Logic ---
        email_cfg = self.config.get('EmailAlert', {})
        if email_cfg.get('enabled') and email_cfg.get('email'):
            self._send_email_report(email_cfg.get('email'), status)

        # Final check if it was cancelled right at the end

        status = 'Cancelled' if self._is_cancel_requested() else 'Completed'
        self._record_history(status)
        self._update_progress(100, status, {'freed_bytes': self.total_freed})


    def _record_history(self, status):
        try:
            import sqlite3, json
            with sqlite3.connect(self.main_db) as conn:
                cursor = conn.cursor()
                job_type = 'Auto_Cleanup' 
                if self.job_id:
                    cursor.execute("SELECT job_type FROM cleanup_jobs WHERE id=?", (self.job_id,))
                    row = cursor.fetchone()
                    if row:
                        job_type = row[0]
                
                cursor.execute('''
                    INSERT INTO cleanup_history (job_id, job_type, user, status, start_time, end_time, config_json, summary_json, freed_bytes)
                    VALUES (?, ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?, ?, ?)
                ''', (self.job_id, job_type, 'admin', status, json.dumps(self.config), json.dumps(getattr(self, 'stats', {})), getattr(self, 'total_freed', 0)))
                conn.commit()
        except Exception as e:
            import logging
            logging.error(f"Error logging final history: {e}")

    def _send_email_report(self, to_email, status):
        try:
            from mail_service import send_email
            import datetime
            import sqlite3
            
            job_type_display = "Automated"
            if self.job_id:
                try:
                    with sqlite3.connect(self.main_db) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT job_type FROM cleanup_jobs WHERE id=?", (self.job_id,))
                        row = cur.fetchone()
                        if row and 'Manual' in row[0]:
                            job_type_display = "Manual"
                except:
                    pass
            
            stats = getattr(self, 'stats', {})
            total_freed = getattr(self, 'total_freed', 0)
            
            total_items = sum(s.get('count', 0) for s in stats.values())
            total_mb = total_freed / (1024*1024)
            
            now_str = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
            job_id_str = str(self.job_id) if self.job_id else "N/A"
            
            # Formatting values
            is_success = status == 'Completed'
            status_color = "#10b981" if is_success else "#ef4444"
            status_bg = "#d1fae5" if is_success else "#fee2e2"
            status_icon = "✓" if is_success else "✗"
            
            # Thematic Colors (Modern Dark/Blue Theme)
            bg_body = "#f4f7f9"
            bg_card = "#ffffff"
            text_main = "#1e293b"
            text_muted = "#64748b"
            accent_blue = "#3b82f6"
            
            rows_html = ""
            for idx, (cat, stat) in enumerate(stats.items()):
                items = stat.get('count', 0)
                mb = stat.get('size', 0) / (1024*1024)
                
                cat_cfg = self.config.get(cat, {})
                strategy = cat_cfg.get('strategy', 'Unknown')
                if strategy == 'older_than_days':
                    policy_str = f"Older than {cat_cfg.get('value', 30)} days"
                elif strategy == 'date_range':
                    policy_str = f"Date range"
                else:
                    policy_str = "Default"
                    
                # Zebra striping for table
                row_bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
                
                rows_html += f'''
                <tr style="background-color: {row_bg};">
                    <td style="padding: 14px 16px; font-size: 14px; font-weight: 600; color: {text_main}; border-bottom: 1px solid #e2e8f0;">{cat}</td>
                    <td style="padding: 14px 16px; font-size: 14px; color: {text_muted}; text-align: right; border-bottom: 1px solid #e2e8f0;">{items:,}</td>
                    <td style="padding: 14px 16px; font-size: 14px; font-weight: 600; color: {accent_blue}; text-align: right; border-bottom: 1px solid #e2e8f0;">{mb:.2f} MB</td>
                    <td style="padding: 14px 16px; font-size: 13px; color: {text_muted}; text-align: right; border-bottom: 1px solid #e2e8f0;">
                        <span style="background: #f1f5f9; padding: 4px 8px; border-radius: 4px; font-size: 12px; border: 1px solid #e2e8f0;">{policy_str}</span>
                    </td>
                </tr>'''

            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    /* Fallback animations for clients that support it (Apple Mail, etc) */
                    @keyframes fadeUp {{
                        from {{ opacity: 0; transform: translateY(15px); }}
                        to {{ opacity: 1; transform: translateY(0); }}
                    }}
                    .animate-box {{
                        animation: fadeUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
                    }}
                    .hover-row:hover {{
                        background-color: #f1f5f9 !important;
                    }}
                </style>
            </head>
            <body style="margin: 0; padding: 0; background-color: {bg_body}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: {bg_body}; padding: 40px 20px;">
                    <tr>
                        <td align="center">
                            <!-- Main Container -->
                            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 650px; background-color: {bg_card}; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05);" class="animate-box">
                                
                                <!-- Header Gradient -->
                                <tr>
                                    <td style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 40px 30px; text-align: center;">
                                        <div style="background: rgba(255,255,255,0.1); width: 60px; height: 60px; border-radius: 50%; display: inline-block; margin-bottom: 15px; line-height: 60px;">
                                            <span style="font-size: 28px;">✨</span>
                                        </div>
                                        <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 700; letter-spacing: -0.5px;">{job_type_display} Cleanup Report</h1>
                                        <p style="margin: 10px 0 0 0; color: #94a3b8; font-size: 14px;">Executed on {now_str}</p>
                                    </td>
                                </tr>
                                
                                <!-- Body Content -->
                                <tr>
                                    <td style="padding: 40px 30px;">
                                        
                                        <!-- Top Info Row -->
                                        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 30px;">
                                            <tr>
                                                <td width="50%" valign="top">
                                                    <p style="margin: 0; font-size: 13px; color: {text_muted}; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Job Reference</p>
                                                    <p style="margin: 4px 0 0 0; font-size: 16px; font-weight: 600; color: {text_main};">#{job_id_str}</p>
                                                </td>
                                                <td width="50%" valign="top" align="right">
                                                    <p style="margin: 0; font-size: 13px; color: {text_muted}; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Status</p>
                                                    <div style="margin-top: 4px; display: inline-block; background-color: {status_bg}; color: {status_color}; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 700;">
                                                        <span style="margin-right: 4px;">{status_icon}</span> {status}
                                                    </div>
                                                </td>
                                            </tr>
                                        </table>

                                        <!-- Highlight Metrics -->
                                        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 35px;">
                                            <tr>
                                                <td width="48%" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 25px 20px; text-align: center;">
                                                    <span style="font-size: 24px; display: block; margin-bottom: 8px;">🗑️</span>
                                                    <p style="margin: 0; font-size: 13px; color: {text_muted}; font-weight: 500;">Items Deleted</p>
                                                    <p style="margin: 5px 0 0 0; font-size: 26px; font-weight: 700; color: {text_main};">{total_items:,}</p>
                                                </td>
                                                <td width="4%"></td>
                                                <td width="48%" style="background-color: #f0f9ff; border: 1px solid #bae6fd; border-radius: 12px; padding: 25px 20px; text-align: center;">
                                                    <span style="font-size: 24px; display: block; margin-bottom: 8px;">💾</span>
                                                    <p style="margin: 0; font-size: 13px; color: #0369a1; font-weight: 500;">Space Freed</p>
                                                    <p style="margin: 5px 0 0 0; font-size: 26px; font-weight: 700; color: #0284c7;">{total_mb:.2f} <span style="font-size: 16px;">MB</span></p>
                                                </td>
                                            </tr>
                                        </table>
                                        
                                        <!-- Table Section -->
                                        <h3 style="margin: 0 0 15px 0; font-size: 16px; font-weight: 600; color: {text_main};">Detailed Breakdown</h3>
                                        <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
                                            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="text-align: left;">
                                                <thead>
                                                    <tr style="background-color: #f8fafc;">
                                                        <th style="padding: 14px 16px; font-size: 12px; color: {text_muted}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Module</th>
                                                        <th style="padding: 14px 16px; font-size: 12px; color: {text_muted}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; text-align: right; border-bottom: 2px solid #e2e8f0;">Items</th>
                                                        <th style="padding: 14px 16px; font-size: 12px; color: {text_muted}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; text-align: right; border-bottom: 2px solid #e2e8f0;">Space</th>
                                                        <th style="padding: 14px 16px; font-size: 12px; color: {text_muted}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; text-align: right; border-bottom: 2px solid #e2e8f0;">Policy</th>
                                                    </tr>
                                                </thead>
                                                <tbody class="hover-row">
                                                    {rows_html}
                                                </tbody>
                                            </table>
                                        </div>
                                        
                                    </td>
                                </tr>
                                
                                <!-- Footer -->
                                <tr>
                                    <td style="background-color: #f8fafc; padding: 25px; text-align: center; border-top: 1px solid #e2e8f0;">
                                        <p style="margin: 0; font-size: 12px; color: #94a3b8; font-weight: 500;">
                                            Generated by <strong>RCM 7021 System Maintenance Engine</strong>
                                        </p>
                                        <p style="margin: 5px 0 0 0; font-size: 11px; color: #cbd5e1;">
                                            This is an automated system message. Please do not reply.
                                        </p>
                                    </td>
                                </tr>
                                
                            </table>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
            '''
            
            subject = f"{job_type_display} Cleanup Report: {status}"
            send_email(to_email, subject, html, body_text=f"Cleanup {status}. Deleted {total_items} items. Freed {total_mb:.2f} MB.")
        except Exception as e:
            import logging
            logging.error(f"Failed to send cleanup email report: {e}")
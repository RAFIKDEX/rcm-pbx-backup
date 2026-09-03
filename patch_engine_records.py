import sqlite3
import json
import os
import glob
import datetime

MAIN_DB = "/root/RCM_7021/rcm_7021.db"
QUEUE_DB = "/root/RCM_7021/rcm_queue.db"
RECORDINGS_DIR = "/var/spool/asterisk/monitor"
OPERATION_LOG = "/etc/asterisk/rcm_pbx_operation_log.json"

with open("/root/RCM_7021/cleanup_engine.py", "r") as f:
    content = f.read()

new_get_date_threshold = """    def get_date_threshold(self, cat_name, cat_cfg):
        strategy = cat_cfg.get('strategy')
        if strategy == 'older_than_days':
            d = datetime.datetime.now() - datetime.timedelta(days=int(cat_cfg.get('value', 30)))
            return d.strftime('%Y-%m-%d %H:%M:%S')
        elif strategy == 'date_range':
            return cat_cfg.get('to', '2030-01-01')
        elif strategy == 'keep_latest_records':
            limit = int(cat_cfg.get('value', 1000))
            if cat_name == 'CDR':
                conn = sqlite3.connect(MAIN_DB)
                c = conn.cursor()
                c.execute("SELECT start_time FROM cdr_records ORDER BY start_time DESC LIMIT 1 OFFSET ?", (limit,))
                row = c.fetchone()
                conn.close()
                return row[0] if row else '1970-01-01'
            elif cat_name == 'Queue_Stats':
                conn = sqlite3.connect(QUEUE_DB)
                c = conn.cursor()
                c.execute("SELECT entry_time FROM queue_calls ORDER BY entry_time DESC LIMIT 1 OFFSET ?", (limit,))
                row = c.fetchone()
                conn.close()
                return row[0] if row else '1970-01-01'
            elif cat_name == 'Zero_Config':
                # Makes no sense for DEX, fallback to safe old date
                return '1970-01-01'
        return '1970-01-01'"""

# Replace get_date_threshold
import re
content = re.sub(r'    def get_date_threshold\(self, cat_cfg\):.*?        return \'1970-01-01\'', new_get_date_threshold, content, flags=re.DOTALL)

# Update scan_cdr
content = content.replace('threshold = self.get_date_threshold(cat)', 'threshold = self.get_date_threshold("CDR", cat)')

# Update scan_queue
content = content.replace('threshold = self.get_date_threshold(cat)', 'threshold = self.get_date_threshold("Queue_Stats", cat)')

# Update scan_dex
content = content.replace('threshold = self.get_date_threshold(cat)', 'threshold = self.get_date_threshold("Zero_Config", cat)')

# We must update scan_recordings and clean_recordings to support keep_latest_records
new_recordings = """    def get_recordings_files_to_delete(self, cat_cfg):
        strategy = cat_cfg.get('strategy')
        files = glob.glob(os.path.join(RECORDINGS_DIR, "*.wav"))
        files.sort(key=os.path.getmtime, reverse=True) # Newest first
        
        if strategy == 'keep_latest_records':
            limit = int(cat_cfg.get('value', 1000))
            return files[limit:]
            
        else:
            threshold_str = self.get_date_threshold('Recordings', cat_cfg)
            try:
                threshold_time = datetime.datetime.strptime(threshold_str, '%Y-%m-%d %H:%M:%S').timestamp()
            except:
                try:
                    threshold_time = datetime.datetime.strptime(threshold_str, '%Y-%m-%d').timestamp()
                except:
                    threshold_time = 0
            return [f for f in files if os.path.getmtime(f) <= threshold_time]

    def scan_recordings(self):
        if not self.config.get("Recordings"): return
        cat = self.config["Recordings"]
        files_to_delete = self.get_recordings_files_to_delete(cat)
        count = len(files_to_delete)
        size = sum(os.path.getsize(f) for f in files_to_delete) if count > 0 else 0
        self.stats["Recordings"] = {"count": count, "size": size, "oldest": "-", "newest": "-"}

    def clean_recordings(self):
        if not self.config.get("Recordings"): return
        cat = self.config["Recordings"]
        files_to_delete = self.get_recordings_files_to_delete(cat)
        for f in files_to_delete:
            try:
                size = os.path.getsize(f)
                os.remove(f)
                self.freed_bytes += size
            except:
                self.failed_count += 1
            if self.check_cancel(): break"""

content = re.sub(r'    def scan_recordings\(self\):.*?            if self\.check_cancel\(\): break', new_recordings, content, flags=re.DOTALL)

# Update operation_log scan and clean
new_oplog = """    def scan_operation_log(self):
        if not self.config.get("Operation_Log"): return
        cat = self.config["Operation_Log"]
        count = 0
        size = 0
        try:
            if os.path.exists(OPERATION_LOG):
                size = os.path.getsize(OPERATION_LOG)
                with open(OPERATION_LOG, "r") as f:
                    data = json.load(f)
                    logs = data.get("logs", [])
                    
                    if cat.get('strategy') == 'keep_latest_records':
                        limit = int(cat.get('value', 1000))
                        count = max(0, len(logs) - limit)
                    else:
                        threshold = self.get_date_threshold("Operation_Log", cat)
                        for log in logs:
                            if log.get('timestamp', '9999-99-99') <= threshold:
                                count += 1
        except Exception:
            pass
        self.stats["Operation_Log"] = {"count": count, "size": size, "oldest": "-", "newest": "-"}

    def clean_operation_log(self):
        if not self.config.get("Operation_Log"): return
        cat = self.config["Operation_Log"]
        try:
            if os.path.exists(OPERATION_LOG):
                with open(OPERATION_LOG, "r") as f:
                    data = json.load(f)
                
                original_logs = data.get("logs", [])
                
                if cat.get('strategy') == 'keep_latest_records':
                    limit = int(cat.get('value', 1000))
                    new_logs = original_logs[-limit:] if limit > 0 else []
                else:
                    threshold = self.get_date_threshold("Operation_Log", cat)
                    new_logs = [log for log in original_logs if log.get('timestamp', '9999-99-99') > threshold]
                
                deleted = len(original_logs) - len(new_logs)
                if deleted > 0:
                    data["logs"] = new_logs
                    with open(OPERATION_LOG + ".tmp", "w") as f:
                        json.dump(data, f)
                    os.replace(OPERATION_LOG + ".tmp", OPERATION_LOG)
                    self.deleted_count += deleted
        except Exception:
            self.failed_count += 1"""

content = re.sub(r'    def scan_operation_log\(self\):.*?            self\.failed_count \+= 1', new_oplog, content, flags=re.DOTALL)

with open("/root/RCM_7021/cleanup_engine.py", "w") as f:
    f.write(content)

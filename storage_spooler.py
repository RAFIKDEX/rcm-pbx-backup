import sqlite3
import os
import json
import datetime
from storage_providers import get_provider_instance

MAIN_DB = "/root/RCM_7021/rcm_7021.db"
RECORDINGS_DIR = "/var/spool/asterisk/monitor"

class StorageSpooler:
    def __init__(self):
        self.conn = sqlite3.connect(MAIN_DB)
        self.conn.row_factory = sqlite3.Row

    def get_absolute_recording_path(self, recording_filename):
        direct_path = os.path.join(RECORDINGS_DIR, recording_filename)
        return direct_path

    def process_new_recordings(self):
        c = self.conn.cursor()
        
        # Load Strategy
        c.execute("SELECT * FROM storage_strategy WHERE id=1")
        strategy = c.fetchone()
        if not strategy or strategy['mode'] == 'local':
            return # Nothing to route

        mode = strategy['mode']
        static_id = strategy['static_provider_id']
        try:
            dynamic_order = json.loads(strategy['dynamic_order_json'])
        except:
            dynamic_order = []

        # Find new recordings not yet tracked in recording_locations
        # Limit to recent to avoid locking PBX, max 100 at a time
        recent_cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute("""
            SELECT c.uniqueid, c.start_time, c.recording 
            FROM cdr_records c
            LEFT JOIN recording_locations rl ON c.uniqueid = rl.cdr_uniqueid
            WHERE c.start_time >= ? 
              AND c.recording != '' 
              AND c.recording IS NOT NULL
              AND rl.id IS NULL
            LIMIT 100
        """, (recent_cutoff,))
        
        new_records = c.fetchall()
        if not new_records:
            return

        for row in new_records:
            uniqueid = row['uniqueid']
            rec_filename = row['recording']
            start_time = row['start_time']
            
            local_path = self.get_absolute_recording_path(rec_filename)
            if not os.path.exists(local_path):
                # File not created yet (call ongoing) or missing. Skip for now.
                continue
                
            file_size = os.path.getsize(local_path)
            
            try:
                dt = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
                ext_path = f"Recordings/{dt.year}/{dt.month:02d}/{dt.day:02d}/{rec_filename}"
            except:
                ext_path = f"Recordings/Unknown/{rec_filename}"

            success = False
            final_ext_path = None
            used_provider_id = None
            
            # Determine providers to try
            providers_to_try = []
            if mode == 'static' and static_id:
                providers_to_try.append(static_id)
            elif mode == 'dynamic':
                providers_to_try.extend([pid for pid in dynamic_order if pid])
                
            # Attempt Upload
            for pid in providers_to_try:
                provider = get_provider_instance(pid)
                if provider and provider.connect():
                    upload_ok, uploaded_path, err = provider.upload_file(local_path, ext_path)
                    if upload_ok:
                        success = True
                        final_ext_path = uploaded_path
                        used_provider_id = pid
                        break # Stop trying next providers
                        
            if success:
                # Update Location Tracker
                c.execute("""
                    INSERT INTO recording_locations 
                    (cdr_uniqueid, local_path, provider_id, external_path, transfer_status, file_size, transferred_at)
                    VALUES (?, ?, ?, ?, 'Success', ?, CURRENT_TIMESTAMP)
                """, (uniqueid, local_path, used_provider_id, final_ext_path, file_size))
                self.conn.commit()
                
                # Safe Delete Local
                keep_local = strategy['keep_local'] if 'keep_local' in strategy.keys() else 0
                if not keep_local:
                    try:
                        os.remove(local_path)
                    except Exception as e:
                        print(f"[SPOOLER] Error deleting local file: {e}")
            else:
                # Failed all external. Mark as local so we don't keep retrying and blocking others.
                # A separate "retry failed" script could handle these later if needed.
                c.execute("""
                    INSERT INTO recording_locations 
                    (cdr_uniqueid, local_path, provider_id, transfer_status, file_size, transferred_at)
                    VALUES (?, ?, NULL, 'Local', ?, CURRENT_TIMESTAMP)
                """, (uniqueid, local_path, file_size))
                self.conn.commit()

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    spooler = StorageSpooler()
    spooler.process_new_recordings()
    spooler.close()

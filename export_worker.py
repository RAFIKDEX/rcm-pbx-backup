import sqlite3
import os
import datetime
import traceback
from storage_providers import get_provider_instance

MAIN_DB = "/root/RCM_7021/rcm_7021.db"
RECORDINGS_DIR = "/var/spool/asterisk/monitor"

class ExportWorker:
    def __init__(self):
        self.conn = sqlite3.connect(MAIN_DB)
        self.conn.row_factory = sqlite3.Row

    def get_absolute_recording_path(self, recording_filename):
        # Depending on Asterisk setup, it might be in subfolders (YYYY/MM/DD)
        # First check direct root
        direct_path = os.path.join(RECORDINGS_DIR, recording_filename)
        if os.path.exists(direct_path):
            return direct_path
            
        # Try to search recursively if needed, but usually Asterisk PBXs store it predictably.
        # For performance, we assume standard paths or direct root.
        # If it has year/month/day in filename like 20260820-1234.wav we could guess, but let's just check direct.
        # RCM might use YYYY/MM/DD/filename.wav in the CDR.
        return direct_path # Adjust if RCM uses nested dirs

    def execute_scheduled_policies(self):
        c = self.conn.cursor()
        
        # Prevent concurrent worker overlapping
        c.execute("SELECT COUNT(*) FROM export_jobs WHERE status IN ('Pending', 'Running') AND job_type='Policy_Auto'")
        if c.fetchone()[0] > 0:
            print("[EXPORT-WORKER] Another auto export job is already running. Skipping.")
            return

        c.execute("SELECT * FROM storage_policies WHERE enabled = 1")
        policies = c.fetchall()

        if not policies:
            return

        for policy in policies:
            self.run_policy(policy)

    def run_policy(self, policy):
        c = self.conn.cursor()
        policy_id = policy['id']
        provider_id = policy['provider_id']
        age_days = policy['age_days']
        action_mode = policy['action_mode'] # move, copy, move_delete, copy_keep
        
        provider = get_provider_instance(provider_id)
        if not provider:
            print(f"[EXPORT-WORKER] Provider {provider_id} not found or invalid.")
            return
            
        if not provider.connect():
            print(f"[EXPORT-WORKER] Failed to connect to provider {provider_id}. Skipping policy {policy_id}.")
            return

        # Calculate threshold date
        threshold_date = (datetime.datetime.now() - datetime.timedelta(days=age_days)).strftime('%Y-%m-%d %H:%M:%S')

        # Find eligible recordings: 
        # 1. Older than threshold
        # 2. Not already transferred to this provider
        # 3. Has a recording file
        query = """
            SELECT c.uniqueid, c.start_time, c.recording 
            FROM cdr_records c
            LEFT JOIN recording_locations rl 
                ON c.uniqueid = rl.cdr_uniqueid AND rl.provider_id = ?
            WHERE c.start_time <= ? 
              AND c.recording != '' 
              AND c.recording IS NOT NULL
              AND rl.id IS NULL
        """
        c.execute(query, (provider_id, threshold_date))
        eligible_records = c.fetchall()

        if not eligible_records:
            return # Nothing to do

        # Create Job
        c.execute("""
            INSERT INTO export_jobs 
            (job_type, policy_id, provider_id, status, total_files, start_time) 
            VALUES ('Policy_Auto', ?, ?, 'Running', ?, CURRENT_TIMESTAMP)
        """, (policy_id, provider_id, len(eligible_records)))
        job_id = c.lastrowid
        self.conn.commit()

        success_count = 0
        failed_count = 0
        skipped_count = 0
        total_size = 0
        errors = []

        print(f"[EXPORT-WORKER] Starting Job {job_id} for Policy {policy_id}. {len(eligible_records)} files to process.")

        for row in eligible_records:
            uniqueid = row['uniqueid']
            rec_filename = row['recording']
            start_time = row['start_time'] # e.g. 2026-08-20 10:00:00
            
            local_path = self.get_absolute_recording_path(rec_filename)
            if not os.path.exists(local_path):
                skipped_count += 1
                continue
                
            file_size = os.path.getsize(local_path)
            
            # Construct standard external path: RCM/Recordings/YYYY/MM/DD/filename.wav
            try:
                dt = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
                ext_path = f"Recordings/{dt.year}/{dt.month:02d}/{dt.day:02d}/{rec_filename}"
            except:
                ext_path = f"Recordings/Unknown/{rec_filename}"

            # Upload!
            success, final_ext_path, err_msg = provider.upload_file(local_path, ext_path)
            
            if success:
                success_count += 1
                total_size += file_size
                
                # Update DB to maintain CDR links
                c.execute("""
                    INSERT INTO recording_locations 
                    (cdr_uniqueid, local_path, provider_id, external_path, transfer_status, file_size, transferred_at)
                    VALUES (?, ?, ?, ?, 'Success', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(cdr_uniqueid) DO UPDATE SET 
                        provider_id=excluded.provider_id, 
                        external_path=excluded.external_path,
                        transfer_status='Success',
                        transferred_at=CURRENT_TIMESTAMP
                """, (uniqueid, local_path, provider_id, final_ext_path, file_size))
                
                # Delete local if required by policy
                if action_mode in ['move', 'move_delete']:
                    try:
                        os.remove(local_path)
                    except Exception as e:
                        errors.append(f"Failed to delete local {uniqueid}: {str(e)}")
                        
            else:
                failed_count += 1
                errors.append(f"Failed {uniqueid}: {err_msg}")
                
            # Periodically commit to save progress
            if (success_count + failed_count + skipped_count) % 50 == 0:
                self.conn.commit()

        # Job Completed
        final_status = 'Completed' if failed_count == 0 else 'Partially Completed'
        if success_count == 0 and failed_count > 0:
            final_status = 'Failed'
            
        error_details = "\n".join(errors[:20]) # Keep top 20 errors to avoid huge text
        if len(errors) > 20:
            error_details += f"\n... and {len(errors)-20} more errors."
            
        c.execute("""
            UPDATE export_jobs 
            SET status=?, success_files=?, failed_files=?, skipped_files=?, 
                total_size_bytes=?, end_time=CURRENT_TIMESTAMP, error_details=?
            WHERE id=?
        """, (final_status, success_count, failed_count, skipped_count, total_size, error_details, job_id))
        self.conn.commit()
        print(f"[EXPORT-WORKER] Job {job_id} Finished. Status: {final_status}.")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    worker = ExportWorker()
    worker.execute_scheduled_policies()
    worker.close()

import sqlite3
import os

MAIN_DB = "/root/RCM_7021/rcm_7021.db"

def init_external_storage_tables():
    conn = sqlite3.connect(MAIN_DB)
    c = conn.cursor()
    
    # 1. Storage Providers
    c.execute('''
        CREATE TABLE IF NOT EXISTS external_storage_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider_type TEXT NOT NULL, 
            enabled INTEGER DEFAULT 1,
            config_json TEXT NOT NULL, 
            status TEXT DEFAULT 'Pending',
            last_error TEXT,
            capacity_bytes INTEGER DEFAULT 0,
            used_bytes INTEGER DEFAULT 0,
            last_sync_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. Storage Policies
    c.execute('''
        CREATE TABLE IF NOT EXISTS storage_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider_id INTEGER NOT NULL,
            age_days INTEGER NOT NULL DEFAULT 30,
            action_mode TEXT NOT NULL, 
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(provider_id) REFERENCES external_storage_providers(id) ON DELETE CASCADE
        )
    ''')
    
    # 3. Export Jobs
    c.execute('''
        CREATE TABLE IF NOT EXISTS export_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            policy_id INTEGER,
            provider_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            total_files INTEGER DEFAULT 0,
            success_files INTEGER DEFAULT 0,
            failed_files INTEGER DEFAULT 0,
            skipped_files INTEGER DEFAULT 0,
            total_size_bytes INTEGER DEFAULT 0,
            start_time TEXT,
            end_time TEXT,
            error_details TEXT,
            FOREIGN KEY(provider_id) REFERENCES external_storage_providers(id) ON DELETE CASCADE
        )
    ''')
    
    # 4. Recording Locations (Links CDR to Storage seamlessly)
    c.execute('''
        CREATE TABLE IF NOT EXISTS recording_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cdr_uniqueid TEXT NOT NULL,
            local_path TEXT,
            provider_id INTEGER,
            external_path TEXT,
            transfer_status TEXT DEFAULT 'Local',
            file_size INTEGER DEFAULT 0,
            checksum TEXT,
            transferred_at TEXT,
            last_error TEXT,
            FOREIGN KEY(provider_id) REFERENCES external_storage_providers(id) ON DELETE SET NULL
        )
    ''')
    # Prevent duplicate records for the same CDR
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_recording_locations_cdr ON recording_locations(cdr_uniqueid)')
    
    # 5. Reports Archive
    c.execute('''
        CREATE TABLE IF NOT EXISTS reports_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            provider_id INTEGER NOT NULL,
            external_path TEXT NOT NULL,
            status TEXT DEFAULT 'Completed',
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(provider_id) REFERENCES external_storage_providers(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()
    print("External Storage tables initialized successfully.")

if __name__ == "__main__":
    init_external_storage_tables()

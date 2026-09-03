import sqlite3
import json
import os

MAIN_DB = "/root/RCM_7021/rcm_7021.db"

def init_cleanup_tables():
    conn = sqlite3.connect(MAIN_DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS cleanup_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL, 
            status TEXT NOT NULL DEFAULT 'Pending',
            progress_percent INTEGER DEFAULT 0,
            progress_details TEXT,
            cancel_requested INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cleanup_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            job_type TEXT NOT NULL,
            user TEXT,
            status TEXT,
            start_time TEXT,
            end_time TEXT,
            config_json TEXT,
            summary_json TEXT,
            freed_bytes INTEGER DEFAULT 0,
            error_details TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cleanup_auto_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enabled INTEGER DEFAULT 0,
            schedule_type TEXT DEFAULT 'daily',
            schedule_time TEXT DEFAULT '03:00',
            rules_json TEXT
        )
    ''')
    
    # Check if there is already a config, if not, insert a default one
    c.execute('SELECT COUNT(*) FROM cleanup_auto_config')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO cleanup_auto_config (enabled, rules_json) VALUES (0, "{}")')

    conn.commit()
    conn.close()
    print("Cleanup tables initialized successfully.")

if __name__ == "__main__":
    init_cleanup_tables()

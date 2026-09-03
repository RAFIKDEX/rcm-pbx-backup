import sqlite3
MAIN_DB = "/root/RCM_7021/rcm_7021.db"

def init_strategy():
    conn = sqlite3.connect(MAIN_DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS storage_strategy (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL DEFAULT 'local',
            static_provider_id INTEGER,
            dynamic_order_json TEXT DEFAULT '[]'
        )
    ''')
    
    c.execute('SELECT COUNT(*) FROM storage_strategy')
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO storage_strategy (id, mode) VALUES (1, 'local')")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_strategy()

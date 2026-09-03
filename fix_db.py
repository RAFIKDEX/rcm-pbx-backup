import os

with open("/root/RCM_7021/db.py", "r") as f:
    content = f.read()

# Find the start of init_db and parse_ini_file
start_idx = content.find("def init_db():")
end_idx = content.find("def parse_ini_file(filepath):")

if start_idx != -1 and end_idx != -1:
    new_init_db = """def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # 2. Extensions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS extensions (
            ext TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            name TEXT,
            callerid_number TEXT,
            secret TEXT,
            max_contacts INTEGER DEFAULT 3,
            max_expiration INTEGER DEFAULT 120,
            ring_time INTEGER DEFAULT 60,
            vm_enabled INTEGER DEFAULT 0,
            vm_password TEXT DEFAULT '1234',
            record_mode TEXT DEFAULT 'noo',
            direct_media INTEGER DEFAULT 0,
            nat INTEGER DEFAULT 0,
            followme_json TEXT DEFAULT '[]',
            mobile TEXT DEFAULT ''
        )
    ''')
    
    # 3. Trunks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trunks (
            name TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            type TEXT NOT NULL,
            register_mode TEXT,
            server_addr TEXT,
            server_port INTEGER DEFAULT 5060,
            keepalive INTEGER DEFAULT 60,
            transport TEXT DEFAULT 'transport-udp',
            outproxy_addr TEXT,
            outproxy_port INTEGER,
            password TEXT,
            username TEXT,
            auth_id TEXT,
            from_user TEXT,
            from_domain TEXT,
            identify_by TEXT DEFAULT 'username'
        )
    ''')

    # 4. Office Time Classes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS office_time_classes (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1
        )
    ''')
    
    # 5. Office Time Rules Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS office_time_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id TEXT,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY(class_id) REFERENCES office_time_classes(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()

    # Check if mobile column exists, if not, add it (migration)
    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN mobile TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    for col, type_def in [("context", "TEXT DEFAULT 'from-trunk'"),
                          ("codecs", "TEXT DEFAULT 'ulaw,alaw'"),
                          ("allowed_ip", "TEXT DEFAULT ''"),
                          ("caller_id", "TEXT DEFAULT ''"),
                          ("qualify", "INTEGER DEFAULT 1")]:
        try:
            cursor.execute(f"ALTER TABLE trunks ADD COLUMN {col} {type_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
            
    # Seed default user if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', hash_password('admin')))
        conn.commit()
        
    # Import existing Asterisk configs if DB is empty
    cursor.execute("SELECT COUNT(*) FROM extensions")
    ext_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM trunks")
    trunk_count = cursor.fetchone()[0]
    
    if ext_count == 0 and trunk_count == 0:
        print("Database is empty. Starting import from existing Asterisk config files...")
        import_existing_configs(conn)
        
    conn.close()

"""
    new_content = content[:start_idx] + new_init_db + content[end_idx:]
    with open("/root/RCM_7021/db.py", "w") as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("FAILED")

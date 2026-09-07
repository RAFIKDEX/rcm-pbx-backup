import sqlite3
import os
import re
import json
import hashlib
import secrets
import string
import threading
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
    PBX_TIMEZONE = ZoneInfo("Africa/Cairo")
except Exception:
    PBX_TIMEZONE = datetime.now().astimezone().tzinfo
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = "/root/RCM_7021/rcm_7021.db"
LDAP_BIND_USERNAME = "cn=user,dc=ippbx,dc=com"
LDAP_BASE_DN = "dc=ippbx,dc=com"
MONITOR_RECORDING_DIR = "/var/spool/asterisk/monitor"
CDR_CSV_PATH = "/var/log/asterisk/cdr-csv/Master.csv"
_CDR_SYNC_LOCK = threading.RLock()
_RECORDING_INDEX = {"folder_mtime": None, "files": []}


def local_datetime_from_epoch(value):
    return datetime.fromtimestamp(float(value), PBX_TIMEZONE).replace(tzinfo=None)


def local_timestamp(value):
    if isinstance(value, datetime):
        naive = value.replace(tzinfo=None)
        return int(naive.replace(tzinfo=PBX_TIMEZONE).timestamp())
    return int(datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=PBX_TIMEZONE).timestamp())

VALID_USER_STATUSES = {"enabled", "disabled"}
VALID_LEGACY_ROLES = {"admin", "supervisor", "agent"}
VALID_PRIVILEGE_SCOPE_TYPES = {"queue_live", "queue_stats", "cdr_reports", "call_records"}
REPORTING_SCOPE_TYPES = tuple(sorted(VALID_PRIVILEGE_SCOPE_TYPES))
REPORTING_SCOPE_GROUPS = {"extensions", "queues", "ring_groups"}

# Config file paths
EP_FILE = "/etc/asterisk/pjsip.gui.endpoint.conf"
AUTH_FILE = "/etc/asterisk/pjsip.gui.auth.conf"
AOR_FILE = "/etc/asterisk/pjsip.gui.aor.conf"
IDENTIFY_FILE = "/etc/asterisk/pjsip.gui.identify.conf"
REG_FILE = "/etc/asterisk/pjsip.gui.reg.conf"
DP_FILE = "/etc/asterisk/extensions_gui.conf"
VM_FILE = "/etc/asterisk/voicemail.conf"
FM_FILE = "/etc/asterisk/followme.conf"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        os.chmod(DB_PATH, 0o666)
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def generate_extension_web_password(length=8):
    """Generate an 8+ character password containing upper, lower and digits."""
    length = max(8, int(length or 8))
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
    ]
    alphabet = string.ascii_letters + string.digits
    chars = required + [secrets.choice(alphabet) for _ in range(length - len(required))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'agent'
        )
    ''')
    
    # 1a. Privileges Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS privileges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            is_protected INTEGER DEFAULT 0,
            system_key TEXT UNIQUE,
            legacy_role TEXT DEFAULT 'agent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 1b. Privilege Permissions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS privilege_permissions (
            privilege_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (privilege_id, module, action),
            FOREIGN KEY (privilege_id) REFERENCES privileges(id) ON DELETE CASCADE
        )
    ''')

    # 1c. Privilege Scope Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS privilege_scope_settings (
            privilege_id INTEGER NOT NULL,
            scope_type TEXT NOT NULL,
            scope_mode TEXT NOT NULL DEFAULT 'all',
            all_data INTEGER NOT NULL DEFAULT 0,
            all_extensions INTEGER NOT NULL DEFAULT 0,
            all_queues INTEGER NOT NULL DEFAULT 0,
            all_ring_groups INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (privilege_id, scope_type),
            FOREIGN KEY (privilege_id) REFERENCES privileges(id) ON DELETE CASCADE
        )
    ''')

    # 1d. Privilege Scope Items Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS privilege_scope_items (
            privilege_id INTEGER NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (privilege_id, scope_type, scope_id),
            FOREIGN KEY (privilege_id) REFERENCES privileges(id) ON DELETE CASCADE
        )
    ''')

    # Reporting scopes originally stored only a flat mode and a list of IDs.
    # Keep those columns for compatibility and add explicit ALL flags so the
    # new grouped scope editor never needs to persist a large list of IDs.
    for column, definition in [
        ("all_data", "INTEGER NOT NULL DEFAULT 0"),
        ("all_extensions", "INTEGER NOT NULL DEFAULT 0"),
        ("all_queues", "INTEGER NOT NULL DEFAULT 0"),
        ("all_ring_groups", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE privilege_scope_settings ADD COLUMN {column} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    
    # 1c. External Contacts & LDAP
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS external_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            number TEXT,
            mobile TEXT,
            other TEXT,
            sync_ldap INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ldap_settings (
            id INTEGER PRIMARY KEY,
            username TEXT,
            password TEXT,
            base_dn TEXT,
            activate INTEGER DEFAULT 0,
            sort_by TEXT DEFAULT 'name'
        )
    ''')
    cursor.execute("""
        INSERT OR IGNORE INTO ldap_settings
            (id, username, password, base_dn, activate, sort_by)
        VALUES
            (1, ?, 'password', ?, 1, 'name')
    """, (LDAP_BIND_USERNAME, LDAP_BASE_DN))
    # The bind identity and directory root are PBX-owned values.  Keep any
    # existing password and service preferences, but canonicalize these two
    # fields so old/custom values cannot leak into the LDAP configuration.
    cursor.execute(
        "UPDATE ldap_settings SET username = ?, base_dn = ? WHERE id = 1",
        (LDAP_BIND_USERNAME, LDAP_BASE_DN),
    )
    
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
            dtmf_mode TEXT DEFAULT 'rfc4733',
            moh_class TEXT DEFAULT 'default',
            video_support INTEGER DEFAULT 0,
            direct_media INTEGER DEFAULT 0,
            nat INTEGER DEFAULT 0,
            codecs TEXT DEFAULT 'alaw,ulaw',
            followme_json TEXT DEFAULT '[]',
            mobile TEXT DEFAULT '',
            allow_spy INTEGER DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS extension_spy_permissions (
            target_ext TEXT NOT NULL,
            allowed_ext TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (target_ext, allowed_ext),
            FOREIGN KEY (target_ext) REFERENCES extensions(ext) ON DELETE CASCADE,
            FOREIGN KEY (allowed_ext) REFERENCES extensions(ext) ON DELETE CASCADE
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_extension_spy_permissions_allowed ON extension_spy_permissions(allowed_ext)")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spy_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            target_ext TEXT,
            caller_ext TEXT,
            mode TEXT,
            result TEXT,
            reason TEXT,
            added_exts TEXT DEFAULT '',
            removed_exts TEXT DEFAULT '',
            username TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spy_audit_created ON spy_audit_log(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spy_audit_target ON spy_audit_log(target_ext)")
    
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

    # 6. Call Center Queue Log Raw table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_queue_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            callid TEXT,
            queuename TEXT,
            agent TEXT,
            event TEXT,
            arg1 TEXT,
            arg2 TEXT,
            arg3 TEXT,
            arg4 TEXT,
            arg5 TEXT,
            processed INTEGER DEFAULT 0
        )
    ''')
    
    # 7. Call Center Calls analytical table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_queue_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            callid TEXT UNIQUE,
            queuename TEXT,
            caller TEXT,
            timestamp INTEGER,
            status TEXT,
            agent TEXT,
            wait_time INTEGER DEFAULT 0,
            talk_time INTEGER DEFAULT 0,
            hold_time INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            hangup_by TEXT,
            recording_file TEXT,
            source_trunk TEXT,
            disposition_code TEXT,
            vip_priority INTEGER DEFAULT 0
        )
    ''')
    
    # 8. Call Center Agent Sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_agent_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT,
            queuename TEXT,
            login_time INTEGER,
            logout_time INTEGER,
            total_online_time INTEGER,
            pause_time INTEGER,
            available_time INTEGER
        )
    ''')
    
    # 9. Call Center Agent Pauses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_agent_pauses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT,
            queuename TEXT,
            pause_time INTEGER,
            unpause_time INTEGER,
            reason TEXT
        )
    ''')

    # 10. Call Center Alerts log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_queue_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            queuename TEXT,
            alert_type TEXT,
            message TEXT,
            resolved INTEGER DEFAULT 0
        )
    ''')

    # 11. Callback requests
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_callback_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            queuename TEXT,
            caller TEXT,
            status TEXT DEFAULT 'pending',
            agent TEXT,
            notes TEXT
        )
    ''')

    # 12. Blacklist/Whitelist table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_caller_lists (
            caller TEXT PRIMARY KEY,
            list_type TEXT
        )
    ''')

    # 13. Feature Codes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_feature_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_name TEXT NOT NULL UNIQUE,
            feature_category TEXT NOT NULL,
            feature_code TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            description TEXT,
            permissions TEXT DEFAULT '',
            destination_number TEXT DEFAULT '',
            timeout INTEGER DEFAULT 15,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 14. Mail Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mail_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT NOT NULL,
            smtp_server TEXT,
            smtp_port INTEGER,
            encryption TEXT,
            sender_email TEXT,
            display_name TEXT DEFAULT '',
            username TEXT,
            password TEXT,
            missed_calls_alert_enabled INTEGER DEFAULT 0,
            missed_calls_threshold INTEGER DEFAULT 5,
            cdr_report_enabled INTEGER DEFAULT 0,
            cdr_report_email TEXT,
            cdr_report_schedule TEXT DEFAULT 'weekly',
            cdr_report_time TEXT DEFAULT '09:00',
            cdr_report_weekday INTEGER DEFAULT 0,
            cdr_report_month_day INTEGER DEFAULT 1
        )
    ''')
    
    # 15. Mail Logs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mail_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_email TEXT,
            sender_email TEXT,
            subject TEXT,
            status TEXT,
            timestamp TEXT,
            error_message TEXT,
            feature TEXT
        )
    ''')
    
    # 16. OTP Records Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otp_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT,
            otp TEXT,
            created_at TEXT,
            expires_at TEXT,
            attempts INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0
        )
    ''')

    # 17. Mail Queue Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mail_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            body_text TEXT,
            attachments_json TEXT,
            feature TEXT,
            attempts INTEGER DEFAULT 0,
            next_retry TEXT,
            created_at TEXT
        )
    ''')

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_qc_timestamp ON rcm_queue_calls(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_qc_queuename ON rcm_queue_calls(queuename)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_qc_agent ON rcm_queue_calls(agent)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_qc_status ON rcm_queue_calls(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ql_callid ON rcm_queue_log(callid)")

    # 18. Inbound Routes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inbound_routes (
            id TEXT PRIMARY KEY,
            name TEXT,
            priority INTEGER,
            data TEXT
        )
    ''')

    # 19. Outbound Routes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outbound_routes (
            name TEXT PRIMARY KEY,
            description TEXT,
            data TEXT
        )
    ''')

    # 20. DOD tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trunk_dods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trunk_id TEXT NOT NULL,
            dod_number TEXT NOT NULL,
            dod_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trunk_id, dod_number)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trunk_dod_extensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trunk_dod_id INTEGER NOT NULL,
            extension_id TEXT NOT NULL,
            UNIQUE(trunk_dod_id, extension_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outbound_route_dods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbound_route_id TEXT NOT NULL,
            dod_number TEXT NOT NULL,
            dod_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(outbound_route_id, dod_number)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outbound_route_dod_extensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbound_route_dod_id INTEGER NOT NULL,
            extension_id TEXT NOT NULL,
            UNIQUE(outbound_route_dod_id, extension_id)
        )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trunk_dods_trunk_id ON trunk_dods(trunk_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trunk_dod_extensions_dod_id ON trunk_dod_extensions(trunk_dod_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outbound_route_dods_route_id ON outbound_route_dods(outbound_route_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outbound_route_dod_extensions_dod_id ON outbound_route_dod_extensions(outbound_route_dod_id)")

    # 20. CDR Records Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cdr_records (
            uniqueid TEXT PRIMARY KEY,
            linkedid TEXT,
            src TEXT,
            dst TEXT,
            clid TEXT,
            channel TEXT,
            dstchannel TEXT,
            dcontext TEXT,
            lastapp TEXT,
            lastdata TEXT,
            start_time TEXT,
            answer_time TEXT,
            end_time TEXT,
            duration INTEGER,
            billsec INTEGER,
            status TEXT,
            recording TEXT,
            userfield TEXT
        )
    ''')

    # CDR userfield carries the structured IVR path for new calls. Keep this
    # migration separate so existing installations receive the column safely.
    try:
        cursor.execute("ALTER TABLE cdr_records ADD COLUMN userfield TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE cdr_records ADD COLUMN linkedid TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cdr_start_time ON cdr_records(start_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cdr_src ON cdr_records(src)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cdr_dst ON cdr_records(dst)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cdr_status ON cdr_records(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cdr_linkedid ON cdr_records(linkedid)")

    # 21. SIP Security Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sip_security_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 0,
            fail2ban_service_enabled INTEGER DEFAULT 1,
            bantime_seconds INTEGER DEFAULT 600,
            findtime_seconds INTEGER DEFAULT 300,
            maxretry INTEGER DEFAULT 10,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    ''')
    try:
        cursor.execute("ALTER TABLE sip_security_settings ADD COLUMN fail2ban_service_enabled INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    cursor.execute("SELECT COUNT(*) FROM sip_security_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO sip_security_settings (id, enabled, bantime_seconds, findtime_seconds, maxretry) VALUES (1, 0, 600, 300, 10)")

    # 22. SIP Security Whitelist Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sip_security_whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value TEXT NOT NULL,
            normalized_network TEXT NOT NULL,
            address_family TEXT NOT NULL,
            prefix_length INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            active INTEGER DEFAULT 1,
            UNIQUE(normalized_network, prefix_length)
        )
    ''')

    # 23. SIP Security Blacklist Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sip_security_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            value TEXT NOT NULL,
            normalized_network TEXT NOT NULL,
            address_family TEXT NOT NULL,
            prefix_length INTEGER NOT NULL,
            reason TEXT,
            starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            removed_at TIMESTAMP,
            removed_by TEXT,
            removal_method TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sip_blacklist_status ON sip_security_blacklist(status)")

    # 24. SIP Security Events Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sip_security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source_ip TEXT,
            source_network TEXT,
            address_family TEXT,
            source_port INTEGER,
            transport TEXT,
            attempted_account TEXT,
            attempt_count INTEGER,
            first_attempt_at TIMESTAMP,
            last_attempt_at TIMESTAMP,
            banned_at TIMESTAMP,
            scheduled_unban_at TIMESTAMP,
            unbanned_at TIMESTAMP,
            jail_name TEXT,
            reason TEXT,
            actor_type TEXT,
            actor_username TEXT,
            status TEXT,
            technical_details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sip_events_created ON sip_security_events(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sip_events_type ON sip_security_events(event_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sip_events_ip ON sip_security_events(source_ip)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sip_events_account ON sip_security_events(attempted_account)")

    # 25. Firewall Rules Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_firewall_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT UNIQUE NOT NULL,
            action TEXT NOT NULL, -- accept, drop
            direction_type TEXT NOT NULL, -- in, out, all
            interface_name TEXT NOT NULL,
            interface_role TEXT,
            source_ip TEXT,
            source_port TEXT,
            source_subnet_mask TEXT,
            destination_ip TEXT,
            destination_port TEXT,
            destination_subnet_mask TEXT,
            protocol TEXT NOT NULL, -- tcp, udp, both
            enabled INTEGER DEFAULT 1,
            apply_status TEXT DEFAULT 'pending', -- applied, pending, error, disabled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    ''')

    # 26. Firewall Events Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rcm_firewall_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_action TEXT NOT NULL, -- apply, delete, fail, revert
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()

    # Run column migrations
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'agent'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    for col, type_def in [
        ("system_key", "TEXT DEFAULT ''"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {type_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN mobile TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN allow_spy INTEGER DEFAULT 1")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN email TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN sync_ldap INTEGER DEFAULT 1")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE mail_settings ADD COLUMN display_name TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    for col, type_def in [
        ("cdr_report_time", "TEXT DEFAULT '09:00'"),
        ("cdr_report_weekday", "INTEGER DEFAULT 0"),
        ("cdr_report_month_day", "INTEGER DEFAULT 1"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE mail_settings ADD COLUMN {col} {type_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN codecs TEXT DEFAULT 'alaw,ulaw'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN dtmf_mode TEXT DEFAULT 'rfc4733'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN moh_class TEXT DEFAULT 'default'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE extensions ADD COLUMN video_support INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    for col, type_def in [("context", "TEXT DEFAULT 'from-trunk'"),
                          ("codecs", "TEXT DEFAULT 'ulaw,alaw'"),
                          ("allowed_ip", "TEXT DEFAULT ''"),
                          ("caller_id", "TEXT DEFAULT ''"),
                          ("qualify", "INTEGER DEFAULT 1"),
                          ("nat", "INTEGER DEFAULT 0"),
                          ("max_expiration", "INTEGER DEFAULT 3600")]:
        try:
            cursor.execute(f"ALTER TABLE trunks ADD COLUMN {col} {type_def}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
            
    # Check users table schema and rebuild safely if needed
    cursor.execute("PRAGMA table_info(users)")
    col_names = [row[1] for row in cursor.fetchall()]
    required_user_columns = {
        'privilege_id', 'status', 'session_version', 'legacy_role', 'system_key',
        'created_at', 'updated_at', 'user_type', 'extension_ext',
        'last_login_at', 'previous_login_at'
    }
    if not required_user_columns.issubset(set(col_names)):
        try:
            cursor.execute("DROP TABLE IF EXISTS users_new")
            cursor.execute('''
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'agent',
                    email TEXT DEFAULT '',
                    privilege_id INTEGER,
                    status TEXT DEFAULT 'enabled',
                    session_version INTEGER DEFAULT 1,
                    legacy_role TEXT DEFAULT 'agent',
                    system_key TEXT DEFAULT '',
                    user_type TEXT NOT NULL DEFAULT 'management',
                    extension_ext TEXT UNIQUE,
                    last_login_at TIMESTAMP,
                    previous_login_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (privilege_id) REFERENCES privileges(id) ON DELETE RESTRICT,
                    FOREIGN KEY (extension_ext) REFERENCES extensions(ext) ON DELETE CASCADE,
                    CHECK (user_type IN ('management', 'extension_user')),
                    CHECK ((user_type = 'extension_user' AND extension_ext IS NOT NULL) OR (user_type = 'management' AND extension_ext IS NULL))
                )
            ''')
            sel_id = "id" if "id" in col_names else "NULL"
            sel_username = "username" if "username" in col_names else "''"
            sel_password = "password" if "password" in col_names else "''"
            sel_role = "role" if "role" in col_names else "'agent'"
            sel_email = "email" if "email" in col_names else "''"
            sel_priv = "privilege_id" if "privilege_id" in col_names else "NULL"
            sel_status = "status" if "status" in col_names else "'enabled'"
            sel_ver = "session_version" if "session_version" in col_names else "1"
            sel_legacy = "legacy_role" if "legacy_role" in col_names else ("role" if "role" in col_names else "'agent'")
            sel_system_key = "system_key" if "system_key" in col_names else "''"
            sel_user_type = "user_type" if "user_type" in col_names else "'management'"
            sel_extension_ext = "extension_ext" if "extension_ext" in col_names else "NULL"
            sel_last_login = "last_login_at" if "last_login_at" in col_names else "NULL"
            sel_previous_login = "previous_login_at" if "previous_login_at" in col_names else "NULL"
            sel_created = "created_at" if "created_at" in col_names else "CURRENT_TIMESTAMP"
            sel_updated = "updated_at" if "updated_at" in col_names else "CURRENT_TIMESTAMP"
            
            cursor.execute(f'''
                INSERT INTO users_new (id, username, password, role, email, privilege_id, status, session_version, legacy_role, system_key, user_type, extension_ext, last_login_at, previous_login_at, created_at, updated_at)
                SELECT {sel_id}, {sel_username}, {sel_password}, {sel_role}, {sel_email}, {sel_priv}, {sel_status}, {sel_ver}, {sel_legacy}, {sel_system_key}, {sel_user_type}, {sel_extension_ext}, {sel_last_login}, {sel_previous_login}, {sel_created}, {sel_updated}
                FROM users
            ''')
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_new RENAME TO users")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_extension_ext ON users(extension_ext) WHERE extension_ext IS NOT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_user_type ON users(user_type)")
            conn.commit()
        except Exception as e:
            print(f"User table migration warning: {e}")
            conn.rollback()

    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_management_users_email_unique
            ON users(lower(email))
            WHERE user_type = 'management' AND trim(COALESCE(email, '')) <> ''
        """)
        conn.commit()
    except sqlite3.IntegrityError:
        # Preserve upgrades that already contain duplicate emails. Route and
        # helper validation still prevents creating additional duplicates.
        conn.rollback()

    # Seed default users if empty
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role, email, status, session_version, legacy_role) VALUES (?, ?, ?, ?, ?, ?, ?)", ('admin', hash_password('admin'), 'admin', 'admin@example.com', 'enabled', 1, 'admin'))
    else:
        cursor.execute("UPDATE users SET role = 'admin', legacy_role = 'admin', email = CASE WHEN email = '' THEN 'admin@example.com' ELSE email END WHERE username = 'admin'")
        
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'supervisor'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role, email, status, session_version, legacy_role) VALUES (?, ?, ?, ?, ?, ?, ?)", ('supervisor', hash_password('supervisor'), 'supervisor', 'supervisor@example.com', 'enabled', 1, 'supervisor'))
    else:
        cursor.execute("UPDATE users SET legacy_role = 'supervisor', email = CASE WHEN email = '' THEN 'supervisor@example.com' ELSE email END WHERE username = 'supervisor'")
        
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'agent'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role, email, status, session_version, legacy_role) VALUES (?, ?, ?, ?, ?, ?, ?)", ('agent', hash_password('agent'), 'agent', 'agent@example.com', 'enabled', 1, 'agent'))
    else:
        cursor.execute("UPDATE users SET legacy_role = 'agent', email = CASE WHEN email = '' THEN 'agent@example.com' ELSE email END WHERE username = 'agent'")
    conn.commit()

    # Seed default Privileges if not exist
    default_privileges = [
        {
            "name": "Super Admin",
            "description": "Built-in System Super Administrator with unrestricted access.",
            "is_protected": 1,
            "system_key": "super_admin",
            "legacy_role": "admin",
            "permissions": [
                ("dashboard", "view"), ("active_calls", "view"), ("active_calls", "hangup"),
                ("extensions", "view"), ("extensions", "add"), ("extensions", "edit"), ("extensions", "delete"), ("extensions", "export"),
                ("trunks", "view"), ("trunks", "add"), ("trunks", "edit"), ("trunks", "delete"), ("trunks", "export"),
                ("inbound_routes", "view"), ("inbound_routes", "add"), ("inbound_routes", "edit"), ("inbound_routes", "delete"),
                ("outbound_routes", "view"), ("outbound_routes", "add"), ("outbound_routes", "edit"), ("outbound_routes", "delete"), ("outbound_routes", "export"),
                ("voice_prompts", "view"), ("voice_prompts", "add"), ("voice_prompts", "edit"), ("voice_prompts", "delete"),
                ("system_prompts", "view"), ("system_prompts", "add"), ("system_prompts", "edit"), ("system_prompts", "delete"),
                ("music_on_hold", "view"), ("music_on_hold", "add"), ("music_on_hold", "edit"), ("music_on_hold", "delete"),
                ("announcements", "view"), ("announcements", "add"), ("announcements", "edit"), ("announcements", "delete"),
                ("paging", "view"), ("paging", "add"), ("paging", "edit"), ("paging", "delete"),
                ("ring_groups", "view"), ("ring_groups", "add"), ("ring_groups", "edit"), ("ring_groups", "delete"),
                ("pickup_groups", "view"), ("pickup_groups", "add"), ("pickup_groups", "edit"), ("pickup_groups", "delete"),
                ("speed_dial", "view"), ("speed_dial", "add"), ("speed_dial", "edit"), ("speed_dial", "delete"),
                ("feature_codes", "view"), ("feature_codes", "edit"),
                ("ivr", "view"), ("ivr", "add"), ("ivr", "edit"), ("ivr", "delete"),
                ("queues", "view"), ("queues", "add"), ("queues", "edit"), ("queues", "delete"), ("queues", "manage_agents"),
                ("global_settings", "view"), ("global_settings", "update"),
                ("time_conditions", "view"), ("time_conditions", "add"), ("time_conditions", "edit"), ("time_conditions", "delete"),
                ("blacklist", "view"), ("blacklist", "add"), ("blacklist", "edit"), ("blacklist", "delete"),
                ("time_settings", "view"), ("time_settings", "update"),
                ("network_settings", "view"), ("network_settings", "update"),
                ("firewall_settings", "view"), ("firewall_settings", "update"),
                ("mail_server", "view"), ("mail_server", "update"), ("mail_server", "test"),
                ("network_troubleshooting", "view"), ("network_troubleshooting", "execute"),
                ("operation_log", "view"), ("operation_log", "export"),
                ("asterisk_restart", "execute"), ("asterisk_reload", "execute"), ("system_reboot", "execute"), ("system_shutdown", "execute"),
                ("users", "view"), ("users", "add"), ("users", "edit"), ("users", "delete"), ("users", "enable"), ("users", "disable"), ("users", "change_password"), ("users", "assign_privilege"),
                ("privileges", "view"), ("privileges", "add"), ("privileges", "edit"), ("privileges", "delete"), ("privileges", "duplicate")
            ],
            "scopes": {
                "queue_live": "all",
                "queue_stats": "all",
                "cdr_reports": "all",
                "call_records": "all"
            }
        },
        {
            "name": "Supervisor",
            "description": "Call Center and PBX Supervisor with full monitoring and view capabilities.",
            "is_protected": 0,
            "system_key": "supervisor",
            "legacy_role": "supervisor",
            "permissions": [
                ("dashboard", "view"), ("active_calls", "view"), ("active_calls", "hangup"),
                ("extensions", "view"), ("trunks", "view"), ("inbound_routes", "view"), ("outbound_routes", "view"),
                ("voice_prompts", "view"), ("music_on_hold", "view"), ("announcements", "view"), ("paging", "view"),
                ("system_prompts", "view"),
                ("ring_groups", "view"), ("pickup_groups", "view"), ("speed_dial", "view"), ("feature_codes", "view"),
                ("ivr", "view"), ("queues", "view"), ("queues", "manage_agents"),
                ("operation_log", "view")
            ],
            "scopes": {
                "queue_live": "all",
                "queue_stats": "all",
                "cdr_reports": "all",
                "call_records": "all"
            }
        },
        {
            "name": "Agent",
            "description": "Standard Call Center Agent.",
            "is_protected": 0,
            "system_key": "agent",
            "legacy_role": "agent",
            "permissions": [
                ("dashboard", "view"), ("active_calls", "view")
            ],
            "scopes": {
                "queue_live": "none",
                "queue_stats": "none",
                "cdr_reports": "none",
                "call_records": "none"
            }
        }
    ]

    for priv in default_privileges:
        cursor.execute("SELECT id FROM privileges WHERE system_key = ?", (priv["system_key"],))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''
                INSERT INTO privileges (name, description, is_protected, system_key, legacy_role)
                VALUES (?, ?, ?, ?, ?)
            ''', (priv["name"], priv["description"], priv["is_protected"], priv["system_key"], priv["legacy_role"]))
            priv_id = cursor.lastrowid
            for mod, act in priv["permissions"]:
                cursor.execute('''
                    INSERT OR IGNORE INTO privilege_permissions (privilege_id, module, action)
                    VALUES (?, ?, ?)
                ''', (priv_id, mod, act))
            for stype, smode in priv["scopes"].items():
                cursor.execute('''
                    INSERT OR REPLACE INTO privilege_scope_settings (privilege_id, scope_type, scope_mode)
                    VALUES (?, ?, ?)
                ''', (priv_id, stype, smode))

    # Upgrade existing built-in roles with the independent System Prompts
    # permissions. INSERT OR IGNORE keeps this migration idempotent and does
    # not alter custom roles or existing built-in permission choices.
    builtin_media_permissions = {
        "super_admin": [("system_prompts", action) for action in ("view", "add", "edit", "delete")],
        "supervisor": [("system_prompts", "view")],
    }
    for system_key, permissions in builtin_media_permissions.items():
        cursor.execute("SELECT id FROM privileges WHERE system_key = ?", (system_key,))
        row = cursor.fetchone()
        if not row:
            continue
        for module, action in permissions:
            cursor.execute('''
                INSERT OR IGNORE INTO privilege_permissions (privilege_id, module, action)
                VALUES (?, ?, ?)
            ''', (row["id"], module, action))

    # One-time compatibility migration: reporting modules used to be stored
    # as normal permissions. Convert their existing scope settings/items into
    # Reporting Data Scope flags, then remove the old permission rows so they
    # no longer appear in the CRUD matrix.
    legacy_reporting_modules = {
        "cdr": "cdr_reports",
        "call_records": "call_records",
        "queue_live": "queue_live",
        "queue_stats": "queue_stats",
    }
    cursor.execute("SELECT id FROM privileges")
    for privilege_row in cursor.fetchall():
        privilege_id = privilege_row["id"]
        cursor.execute(
            "SELECT DISTINCT module FROM privilege_permissions WHERE privilege_id = ? AND module IN (?, ?, ?, ?)",
            (privilege_id, *legacy_reporting_modules.keys()),
        )
        legacy_modules = [row["module"] for row in cursor.fetchall()]
        if not legacy_modules:
            continue
        for legacy_module in legacy_modules:
            scope_type = legacy_reporting_modules[legacy_module]
            cursor.execute("SELECT scope_mode FROM privilege_scope_settings WHERE privilege_id = ? AND scope_type = ?", (privilege_id, scope_type))
            setting = cursor.fetchone()
            mode = setting["scope_mode"] if setting else "all"
            all_data = 0
            all_extensions = 0
            all_queues = 0
            all_ring_groups = 0
            if mode == "all":
                if scope_type in ("queue_live", "queue_stats"):
                    all_queues = 1
                else:
                    all_data = 1
            elif mode == "selected":
                cursor.execute("SELECT scope_id FROM privilege_scope_items WHERE privilege_id = ? AND scope_type = ?", (privilege_id, scope_type))
                legacy_items = [str(row["scope_id"]) for row in cursor.fetchall()]
                group = "queues" if scope_type in ("queue_live", "queue_stats") else "extensions"
                for item in legacy_items:
                    cursor.execute(
                        "INSERT OR IGNORE INTO privilege_scope_items (privilege_id, scope_type, scope_id) VALUES (?, ?, ?)",
                        (privilege_id, scope_type, _reporting_scope_item(group, item)),
                    )
            cursor.execute("""
                UPDATE privilege_scope_settings
                SET scope_mode = ?, all_data = ?, all_extensions = ?, all_queues = ?, all_ring_groups = ?, updated_at = CURRENT_TIMESTAMP
                WHERE privilege_id = ? AND scope_type = ?
            """, ("all" if all_data else ("selected" if mode == "selected" else "none"), all_data, all_extensions, all_queues, all_ring_groups, privilege_id, scope_type))
            if not setting:
                cursor.execute("""
                    INSERT INTO privilege_scope_settings
                        (privilege_id, scope_type, scope_mode, all_data, all_extensions, all_queues, all_ring_groups)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (privilege_id, scope_type, "all" if all_data else ("selected" if mode == "selected" else "none"), all_data, all_extensions, all_queues, all_ring_groups))
        placeholders = ",".join("?" for _ in legacy_reporting_modules)
        cursor.execute(
            f"DELETE FROM privilege_permissions WHERE privilege_id = ? AND module IN ({placeholders})",
            (privilege_id, *legacy_reporting_modules.keys()),
        )
    # Canonicalize any raw IDs left by the legacy scope table. This is
    # idempotent and keeps the new grouped editor from seeing duplicates.
    cursor.execute("SELECT privilege_id, scope_type, scope_id FROM privilege_scope_items WHERE instr(scope_id, ':') = 0")
    for item_row in cursor.fetchall():
        scope_type = item_row["scope_type"]
        if scope_type not in VALID_PRIVILEGE_SCOPE_TYPES:
            continue
        group = "queues" if scope_type in ("queue_live", "queue_stats") else "extensions"
        canonical = _reporting_scope_item(group, item_row["scope_id"])
        cursor.execute(
            "INSERT OR IGNORE INTO privilege_scope_items (privilege_id, scope_type, scope_id) VALUES (?, ?, ?)",
            (item_row["privilege_id"], scope_type, canonical),
        )
        cursor.execute(
            "DELETE FROM privilege_scope_items WHERE privilege_id = ? AND scope_type = ? AND scope_id = ?",
            (item_row["privilege_id"], scope_type, item_row["scope_id"]),
        )
    conn.commit()

    # Link existing users to seeded privileges
    cursor.execute("SELECT id FROM privileges WHERE system_key = 'super_admin'")
    super_admin_row = cursor.fetchone()
    super_admin_id = super_admin_row["id"] if super_admin_row else None

    cursor.execute("SELECT id FROM privileges WHERE system_key = 'supervisor'")
    super_row = cursor.fetchone()
    supervisor_id = super_row["id"] if super_row else None

    cursor.execute("SELECT id FROM privileges WHERE system_key = 'agent'")
    agent_row = cursor.fetchone()
    agent_id = agent_row["id"] if agent_row else None

    if super_admin_id:
        cursor.execute("UPDATE users SET privilege_id = ?, legacy_role = 'admin' WHERE username = 'admin' OR role = 'admin'", (super_admin_id,))
    if supervisor_id:
        cursor.execute("UPDATE users SET privilege_id = ?, legacy_role = 'supervisor' WHERE username = 'supervisor' OR role = 'supervisor'", (supervisor_id,))
    if agent_id:
        cursor.execute("UPDATE users SET privilege_id = ?, legacy_role = 'agent' WHERE user_type = 'management' AND (username = 'agent' OR (role != 'admin' AND role != 'supervisor' AND (privilege_id IS NULL OR privilege_id = '')))", (agent_id,))
    conn.commit()
        
    # Seed default feature codes if empty
    cursor.execute("SELECT COUNT(*) FROM rcm_feature_codes")
    if cursor.fetchone()[0] == 0:
        default_features = [
            {"name": "My Voicemail", "category": "Voicemail", "code": "*97", "enabled": 1, "description": "Access personal voicemail inbox", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Voicemail Access Code", "category": "Voicemail", "code": "*98", "enabled": 1, "description": "Access voicemail system for any mailbox", "permissions": "admin,supervisor", "dest": "", "timeout": 0},
            {"name": "DND Activate", "category": "Presence & Availability", "code": "*37", "enabled": 1, "description": "Enable Do Not Disturb (DND)", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "DND Deactivate", "category": "Presence & Availability", "code": "*38", "enabled": 1, "description": "Disable Do Not Disturb (DND)", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "General Call Pickup", "category": "Call Pickup", "code": "*8", "enabled": 1, "description": "Pick up any ringing call in the pickup group", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Direct Call Pickup", "category": "Call Pickup", "code": "**", "enabled": 1, "description": "Pick up a ringing call on a specific extension", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Blind Transfer", "category": "Call Transfer", "code": "##", "enabled": 1, "description": "Transfer call directly without talking to recipient", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Attended Transfer", "category": "Call Transfer", "code": "*2", "enabled": 1, "description": "Talk to recipient before completing transfer", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Abort Transfer", "category": "Call Transfer", "code": "*1", "enabled": 1, "description": "Cancel active attended transfer", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Listen Spy", "category": "Call Monitoring", "code": "*54", "enabled": 1, "description": "Listen to a live call quietly", "permissions": "admin,supervisor", "dest": "", "timeout": 0},
            {"name": "Whisper", "category": "Call Monitoring", "code": "*55", "enabled": 1, "description": "Listen to a live call and speak to the protected extension only", "permissions": "admin,supervisor", "dest": "", "timeout": 0},
            {"name": "Barge", "category": "Call Monitoring", "code": "*56", "enabled": 1, "description": "Barge into a live call to speak with both parties", "permissions": "admin,supervisor", "dest": "", "timeout": 0},
            {"name": "Queue Login", "category": "Queue Management", "code": "*71", "enabled": 1, "description": "Log in to queues dynamically", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Queue Logout", "category": "Queue Management", "code": "*72", "enabled": 1, "description": "Log out from dynamic queues", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Queue Pause", "category": "Queue Management", "code": "*73", "enabled": 1, "description": "Pause queue call receiving", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Queue Unpause", "category": "Queue Management", "code": "*74", "enabled": 1, "description": "Resume queue call receiving", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Public Queue Pause", "category": "Queue Management", "code": "*75", "enabled": 1, "description": "Pause this agent in every queue they are currently logged into", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Public Queue Unpause", "category": "Queue Management", "code": "*76", "enabled": 1, "description": "Unpause this agent in every queue they are currently paused in", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
            {"name": "Forward Always Activate", "category": "Call Forwarding", "code": "*64", "enabled": 1, "description": "Activate Forward Always", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15},
            {"name": "Forward Always Deactivate", "category": "Call Forwarding", "code": "*65", "enabled": 1, "description": "Deactivate Forward Always", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15},
            {"name": "Forward Busy Activate", "category": "Call Forwarding", "code": "*58", "enabled": 1, "description": "Activate Forward on Busy", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15},
            {"name": "Forward Busy Deactivate", "category": "Call Forwarding", "code": "*59", "enabled": 1, "description": "Deactivate Forward on Busy", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15},
            {"name": "Forward No Answer Activate", "category": "Call Forwarding", "code": "*60", "enabled": 1, "description": "Activate Forward on No Answer", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15},
            {"name": "Forward No Answer Deactivate", "category": "Call Forwarding", "code": "*61", "enabled": 1, "description": "Deactivate Forward on No Answer", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 15}
        ]
        for f in default_features:
            cursor.execute('''
                INSERT INTO rcm_feature_codes 
                (feature_name, feature_category, feature_code, enabled, description, permissions, destination_number, timeout)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (f["name"], f["category"], f["code"], f["enabled"], f["description"], f["permissions"], f["dest"], f["timeout"]))
        conn.commit()

    missing_default_features = [
        {"name": "Public Queue Pause", "category": "Queue Management", "code": "*75", "enabled": 1, "description": "Pause this agent in every queue they are currently logged into", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
        {"name": "Public Queue Unpause", "category": "Queue Management", "code": "*76", "enabled": 1, "description": "Unpause this agent in every queue they are currently paused in", "permissions": "admin,supervisor,agent", "dest": "", "timeout": 0},
    ]
    for f in missing_default_features:
        cursor.execute("SELECT COUNT(*) FROM rcm_feature_codes WHERE feature_name = ?", (f["name"],))
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO rcm_feature_codes
                (feature_name, feature_category, feature_code, enabled, description, permissions, destination_number, timeout)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (f["name"], f["category"], f["code"], f["enabled"], f["description"], f["permissions"], f["dest"], f["timeout"]))
    conn.commit()
        
    # Import existing Asterisk configs if DB is empty
    cursor.execute("SELECT COUNT(*) FROM extensions")
    ext_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM trunks")
    trunk_count = cursor.fetchone()[0]
    
    if ext_count == 0 and trunk_count == 0:
        print("Database is empty. Starting import from existing Asterisk config files...")
        import_existing_configs(conn)

    # Idempotent extension-user migration. Existing hashes are never replaced.
    ensure_extension_web_users(conn)

    # DEX owns its additive schema and reference data.  The migration module
    # uses a savepoint and never alters existing production tables.
    conn.close()

def parse_ini_file(filepath):
    """Simple parser for Asterisk ini-like files."""
    if not os.path.exists(filepath):
        return {}
    sections = {}
    current_section = None
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line_str = line.strip()
            # Skip comments and empty lines, unless it's rcm_max_contacts
            if not line_str:
                continue
            if line_str.startswith(';'):
                m = re.match(r'^;\s*(rcm_max_contacts)\s*=\s*(.+)$', line_str)
                if m and current_section:
                    sections[current_section][m.group(1)] = m.group(2).strip()
                continue
            
            # Section header
            if line_str.startswith('[') and line_str.endswith(']'):
                current_section = line_str[1:-1].strip()
                sections[current_section] = {}
                continue
            
            # Key-value pair
            if '=' in line_str and current_section:
                parts = line_str.split('=', 1)
                k = parts[0].strip()
                v = parts[1].strip()
                sections[current_section][k] = v
                
    return sections

def import_existing_configs(conn):
    cursor = conn.cursor()
    
    # Parse PJSIP configs
    endpoints = parse_ini_file(EP_FILE)
    auths = parse_ini_file(AUTH_FILE)
    aors = parse_ini_file(AOR_FILE)
    identifies = parse_ini_file(IDENTIFY_FILE)
    registrations = parse_ini_file(REG_FILE)
    
    # Parse extensions_gui.conf globals for ring time, VM and recording
    globals_dict = {}
    if os.path.exists(DP_FILE):
        in_globals = False
        with open(DP_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                t = line.strip()
                if t == '[globals]':
                    in_globals = True
                    continue
                elif t.startswith('['):
                    in_globals = False
                if in_globals and '=' in t and not t.startswith(';'):
                    k, v = [x.strip() for x in t.split('=', 1)]
                    globals_dict[k] = v

    # Parse voicemail.conf
    voicemails = {}
    if os.path.exists(VM_FILE):
        in_default = False
        with open(VM_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                t = line.strip()
                if t == '[default]':
                    in_default = True
                    continue
                elif t.startswith('['):
                    in_default = False
                if in_default and '=>' in t and not t.startswith(';'):
                    parts = t.split('=>', 1)
                    vm_ext = parts[0].strip()
                    vm_data = [x.strip() for x in parts[1].split(',')]
                    voicemails[vm_ext] = vm_data[0] if len(vm_data) > 0 else '1234'

    # Parse followme.conf
    followmes = {}
    if os.path.exists(FM_FILE):
        current_fm = None
        with open(FM_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                t = line.strip()
                if t.startswith('[') and t.endswith(']'):
                    current_fm = t[1:-1].strip()
                    if current_fm not in ['general', 'default']:
                        followmes[current_fm] = []
                    else:
                        current_fm = None
                elif current_fm and t.startswith('number') and '=>' in t:
                    # number => num,ring
                    parts = t.split('=>', 1)[1].split(',')
                    num = parts[0].strip()
                    ring = int(parts[1].strip()) if len(parts) > 1 else 15
                    followmes[current_fm].append({"number": num, "ring": ring})

    # Identify Trunks
    # Trunks are sections in pjsip.gui.endpoint.conf that are NOT numeric, OR identified by markers
    # Let's read pjsip.gui.endpoint.conf and get all trunk names from RCM markers if possible, or sections
    trunk_names = set()
    if os.path.exists(EP_FILE):
        with open(EP_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            matches = re.findall(r';\s*---\s*RCM-TRUNK:\s*([^\s]+)\s*BEGIN\s*---', content)
            for m in matches:
                trunk_names.add(m)

    # Let's also look in identify file
    if os.path.exists(IDENTIFY_FILE):
        with open(IDENTIFY_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            matches = re.findall(r';\s*---\s*RCM-TRUNK:\s*([^\s]+)\s*BEGIN\s*---', content)
            for m in matches:
                trunk_names.add(m)

    # 1. Process Extensions (numeric sections in endpoints)
    for ext, ep in endpoints.items():
        if not ext.isdigit():
            continue
        
        # Get name & callerid
        cid_str = ep.get("callerid", "")
        name = ""
        cid_num = ext
        if cid_str:
            m = re.match(r'^"?([^"<]*)"?\s*<([^>]*)>', cid_str)
            if m:
                name = m.group(1).strip()
                cid_num = m.group(2).strip()
            else:
                cid_num = cid_str.strip()
                
        # Secret
        secret = auths.get(ext, {}).get("password", "Abc@1234")
        
        # Max contacts & Enabled
        aor = aors.get(ext, {})
        rcm_max_contacts = aor.get("rcm_max_contacts")
        if rcm_max_contacts:
            max_contacts = int(rcm_max_contacts)
        else:
            max_contacts = int(aor.get("max_contacts", 3))
            
        enabled = 1
        if int(aor.get("max_contacts", 3)) == 0:
            enabled = 0
            
        max_expiration = int(aor.get("maximum_expiration", 120))
        
        # Ring time
        ring_time = int(globals_dict.get(f"RING_{ext}", 60))
        
        # Voicemail
        vm_enabled = 1 if globals_dict.get(f"VM_{ext}", "Off").lower() == "on" else 0
        vm_password = voicemails.get(ext, "1234")
        
        # Record mode
        record_mode = str(globals_dict.get(f"RECORD_{ext}", "noo") or "noo").strip().lower()
        if record_mode in ("", "no", "oo"):
            record_mode = "noo"
        
        # Media options
        direct_media = 1 if ep.get("direct_media", "no").lower() in ["yes", "true"] else 0
        nat = 1 if ep.get("rtp_symmetric", "no").lower() in ["yes", "true"] else 0
        codecs = ep.get("allow", "alaw,ulaw")
        
        # Follow me
        fm_list = followmes.get(ext, [])
        fm_json = json.dumps(fm_list)
        
        # Insert extension
        cursor.execute('''
            INSERT OR REPLACE INTO extensions 
            (ext, enabled, name, callerid_number, secret, max_contacts, max_expiration, ring_time, vm_enabled, vm_password, record_mode, direct_media, nat, codecs, followme_json, mobile, allow_spy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ext, enabled, name, cid_num, secret, max_contacts, max_expiration, ring_time, vm_enabled, vm_password, record_mode, direct_media, nat, codecs, fm_json, '', 1))
        
    # 2. Process Trunks
    for trunk in trunk_names:
        ep = endpoints.get(trunk, {})
        aor = aors.get(trunk, aors.get(f"{trunk}-aor", {}))
        auth = auths.get(f"{trunk}-auth", auths.get(trunk, {}))
        identify = identifies.get(f"{trunk}_identify", {})
        reg = registrations.get(f"{trunk}-reg", {})
        
        enabled = 1
        
        # Determine Trunk type and registration mode
        trunk_type = "peer"
        reg_mode = None
        
        if reg:
            trunk_type = "register"
            reg_mode = "client"
        elif auth and ep.get("auth") == f"{trunk}-auth":
            trunk_type = "register"
            reg_mode = "server"
        else:
            trunk_type = "peer"
            
        # Parse fields
        server_addr = ""
        server_port = 5060
        
        if trunk_type == "peer":
            contact = aor.get("contact", "")
            if contact.startswith("sip:"):
                host_port = contact[4:]
                if ':' in host_port:
                    server_addr, port_str = host_port.split(':', 1)
                    server_port = int(port_str) if port_str.isdigit() else 5060
                else:
                    server_addr = host_port
            else:
                server_addr = identify.get("match", "")
        elif reg_mode == "client":
            srv_uri = reg.get("server_uri", "")
            if srv_uri.startswith("sip:"):
                host_port = srv_uri[4:]
                if ':' in host_port:
                    server_addr, port_str = host_port.split(':', 1)
                    server_port = int(port_str) if port_str.isdigit() else 5060
                else:
                    server_addr = host_port
        elif reg_mode == "server":
            server_addr = "" # Incoming registrations register to us
            
        keepalive = int(aor.get("qualify_frequency", 60))
        transport = ep.get("transport", "transport-udp")
        
        password = auth.get("password", "")
        username = auth.get("username", "") if reg_mode == "client" else trunk
        auth_id = auth.get("username", "") if reg_mode == "client" else ""
        
        outproxy_addr = ""
        outproxy_port = None
        outbound_proxy = reg.get("outbound_proxy", "")
        if outbound_proxy.startswith("sip:"):
            proxy_host = outbound_proxy[4:].split(';')[0]
            if ':' in proxy_host:
                outproxy_addr, proxy_port_str = proxy_host.split(':', 1)
                outproxy_port = int(proxy_port_str) if proxy_port_str.isdigit() else None
            else:
                outproxy_addr = proxy_host
                
        from_user = reg.get("from_user", "")
        from_domain = reg.get("from_domain", "")
        identify_by = ep.get("identify_by", "username")
        
        # Parse new properties
        context = ep.get("context", "from-trunk")
        codecs = ep.get("allow", "ulaw,alaw")
        allowed_ip = identify.get("match", "")
        caller_id = ep.get("callerid", "")
        qualify = 0 if int(aor.get("qualify_frequency", 60)) == 0 else 1

        cursor.execute('''
            INSERT OR REPLACE INTO trunks 
            (name, enabled, type, register_mode, server_addr, server_port, keepalive, transport, outproxy_addr, outproxy_port, password, username, auth_id, from_user, from_domain, identify_by,
             context, codecs, allowed_ip, caller_id, qualify)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (trunk, enabled, trunk_type, reg_mode, server_addr, server_port, keepalive, transport, outproxy_addr, outproxy_port, password, username, auth_id, from_user, from_domain, identify_by,
              context, codecs, allowed_ip, caller_id, qualify))
        
    conn.commit()
    print("Database sync completed.")

# Extension Database Helpers
def _create_extension_web_user(cursor, ext, email="", web_password=None):
    ext = str(ext).strip()
    cursor.execute("SELECT id, user_type, extension_ext FROM users WHERE username = ?", (ext,))
    username_owner = cursor.fetchone()
    if username_owner:
        owner = dict(username_owner)
        if owner.get("user_type") == "extension_user" and owner.get("extension_ext") == ext:
            return None
        raise ValueError(f"Cannot create Web User {ext}: that username is already used by another account.")

    password_once = str(web_password or "").strip() or generate_extension_web_password()
    cursor.execute("""
        INSERT INTO users
        (username, password, role, email, privilege_id, status, session_version,
         legacy_role, system_key, user_type, extension_ext, created_at, updated_at)
        VALUES (?, ?, 'extension_user', ?, NULL, 'enabled', 1,
                'extension_user', '', 'extension_user', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (ext, generate_password_hash(password_once), email or "", ext))
    return password_once

def ensure_extension_web_users(conn=None):
    """Create missing extension users without ever replacing an existing password."""
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    cursor = conn.cursor()
    created = 0
    try:
        cursor.execute("""
            SELECT e.ext, COALESCE(e.email, '') AS email
            FROM extensions e
            LEFT JOIN users u ON u.extension_ext = e.ext AND u.user_type = 'extension_user'
            WHERE u.id IS NULL
            ORDER BY e.ext
        """)
        missing = [dict(row) for row in cursor.fetchall()]
        for extension in missing:
            _create_extension_web_user(cursor, extension["ext"], extension.get("email", ""))
            created += 1
        conn.commit()
        return created
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

def get_extension_web_user(ext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM users
        WHERE user_type = 'extension_user' AND extension_ext = ? AND username = ?
    """, (str(ext), str(ext)))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_extension_web_password(ext, new_password, current_password=None):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE user_type = 'extension_user' AND extension_ext = ?", (str(ext),))
        row = cursor.fetchone()
        if not row:
            return False, "Extension Web User not found."
        user = dict(row)
        if current_password is not None and not _password_matches_hash(user["password"], current_password):
            return False, "Current Web Password is incorrect."
        cursor.execute("""
            UPDATE users
            SET password = ?, session_version = COALESCE(session_version, 1) + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (generate_password_hash(new_password), user["id"]))
        conn.commit()
        return True, ""
    except Exception as exc:
        conn.rollback()
        return False, str(exc)
    finally:
        conn.close()

def get_all_extensions():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM extensions ORDER BY ext")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_extension(ext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM extensions WHERE ext = ?", (ext,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_active_extensions(exclude_ext=None):
    conn = get_db()
    cursor = conn.cursor()
    if exclude_ext is None:
        cursor.execute("SELECT * FROM extensions WHERE enabled = 1 ORDER BY ext")
    else:
        cursor.execute("SELECT * FROM extensions WHERE enabled = 1 AND ext != ? ORDER BY ext", (str(exclude_ext),))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_spy_permissions_for_target(target_ext):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT allowed_ext
        FROM extension_spy_permissions
        WHERE target_ext = ?
        ORDER BY allowed_ext
    """, (str(target_ext),))
    rows = [str(row["allowed_ext"]) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_all_spy_permissions():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT target_ext, allowed_ext
        FROM extension_spy_permissions
        ORDER BY target_ext, allowed_ext
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def is_spy_allowed(caller_ext, target_ext):
    caller_ext = str(caller_ext or "").strip()
    target_ext = str(target_ext or "").strip()
    if not caller_ext or not target_ext or caller_ext == target_ext:
        return False
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1
        FROM extension_spy_permissions
        WHERE target_ext = ? AND allowed_ext = ?
        LIMIT 1
    """, (target_ext, caller_ext))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

def validate_spy_permission_selection(target_ext, allowed_exts, include_target_exists=True):
    target_ext = str(target_ext or "").strip()
    selected = []
    seen = set()
    for value in allowed_exts or []:
        value = str(value or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        selected.append(value)

    if target_ext in seen:
        return False, "An extension cannot be allowed to spy on itself.", []

    conn = get_db()
    cursor = conn.cursor()
    if include_target_exists:
        cursor.execute("SELECT enabled FROM extensions WHERE ext = ?", (target_ext,))
        target = cursor.fetchone()
        if not target:
            conn.close()
            return False, f"Target extension {target_ext} does not exist.", []

    if selected:
        placeholders = ",".join(["?"] * len(selected))
        cursor.execute(f"SELECT ext FROM extensions WHERE enabled = 1 AND ext IN ({placeholders})", selected)
        active = {str(row["ext"]) for row in cursor.fetchall()}
    else:
        active = set()
    conn.close()

    invalid = [ext for ext in selected if ext not in active]
    if invalid:
        return False, f"Allowed Spy Extension(s) are invalid or inactive: {', '.join(invalid)}.", []
    return True, "", selected

def set_spy_permissions_for_target(target_ext, allowed_exts, conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    cursor = conn.cursor()
    target_ext = str(target_ext)
    normalized = []
    for ext in allowed_exts or []:
        ext = str(ext).strip()
        if ext and ext not in normalized:
            normalized.append(ext)
    cursor.execute("SELECT allowed_ext FROM extension_spy_permissions WHERE target_ext = ?", (target_ext,))
    old = {str(row["allowed_ext"]) for row in cursor.fetchall()}
    new = set(normalized)
    added = sorted(new - old)
    removed = sorted(old - new)
    cursor.execute("DELETE FROM extension_spy_permissions WHERE target_ext = ?", (target_ext,))
    cursor.executemany(
        "INSERT INTO extension_spy_permissions (target_ext, allowed_ext) VALUES (?, ?)",
        [(target_ext, allowed_ext) for allowed_ext in sorted(new)]
    )
    if own_conn:
        conn.commit()
        conn.close()
    return added, removed

def add_extension_with_spy_permissions(data, allowed_spy_exts):
    ok, msg, normalized = validate_spy_permission_selection(data.get("ext"), allowed_spy_exts, include_target_exists=False)
    if not ok:
        return False, msg, [], []
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        cursor.execute('''
            INSERT INTO extensions 
            (ext, enabled, name, callerid_number, secret, max_contacts, max_expiration, ring_time, vm_enabled, vm_password, record_mode, dtmf_mode, moh_class, video_support, direct_media, nat, codecs, followme_json, mobile, allow_spy, email, sync_ldap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data["ext"], data["enabled"], data["name"], data["callerid_number"], data["secret"],
            data["max_contacts"], data["max_expiration"], data["ring_time"], data["vm_enabled"],
            data["vm_password"], data["record_mode"], data.get("dtmf_mode", "rfc4733"), data.get("moh_class", "default"), int(data.get("video_support", 0) or 0), data["direct_media"], data["nat"],
            data.get("codecs", "alaw,ulaw"), json.dumps(data.get("followme", [])), data.get("mobile", ""),
            data.get("allow_spy", 1), data.get("email", ""), data.get("sync_ldap", 1)
        ))
        data["_web_password_once"] = _create_extension_web_user(
            cursor, data["ext"], data.get("email", ""), data.get("web_password")
        )
        added, removed = set_spy_permissions_for_target(data["ext"], normalized, conn=conn)
        conn.commit()
        return True, "", added, removed
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, f"Extension {data.get('ext')} could not be added. It may already exist.", [], []
    except Exception as e:
        conn.rollback()
        return False, str(e), [], []
    finally:
        conn.close()

def update_extension_with_spy_permissions(ext, data, allowed_spy_exts):
    ok, msg, normalized = validate_spy_permission_selection(ext, allowed_spy_exts, include_target_exists=True)
    if not ok:
        return False, msg, [], []
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        cursor.execute('''
            UPDATE extensions SET
                enabled = ?, name = ?, callerid_number = ?, secret = ?, max_contacts = ?, 
                max_expiration = ?, ring_time = ?, vm_enabled = ?, vm_password = ?, 
                record_mode = ?, dtmf_mode = ?, moh_class = ?, video_support = ?, direct_media = ?, nat = ?, codecs = ?, followme_json = ?, mobile = ?,
                allow_spy = ?, email = ?, sync_ldap = ?
            WHERE ext = ?
        ''', (
            data["enabled"], data["name"], data["callerid_number"], data["secret"],
            data["max_contacts"], data["max_expiration"], data["ring_time"], data["vm_enabled"],
            data["vm_password"], data["record_mode"], data.get("dtmf_mode", "rfc4733"), data.get("moh_class", "default"), int(data.get("video_support", 0) or 0), data["direct_media"], data["nat"],
            data.get("codecs", "alaw,ulaw"), json.dumps(data.get("followme", [])), data.get("mobile", ""),
            data.get("allow_spy", 1), data.get("email", ""), data.get("sync_ldap", 1), ext
        ))
        if cursor.rowcount == 0:
            raise ValueError(f"Extension {ext} not found.")
        web_password = str(data.get("web_password") or "").strip()
        if web_password:
            cursor.execute("""
                UPDATE users
                SET password = ?, email = ?, session_version = COALESCE(session_version, 1) + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_type = 'extension_user' AND extension_ext = ?
            """, (generate_password_hash(web_password), data.get("email", ""), str(ext)))
            if cursor.rowcount != 1:
                raise ValueError(f"Web User for extension {ext} not found.")
        else:
            cursor.execute("""
                UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_type = 'extension_user' AND extension_ext = ?
            """, (data.get("email", ""), str(ext)))
        added, removed = set_spy_permissions_for_target(ext, normalized, conn=conn)
        conn.commit()
        return True, "", added, removed
    except Exception as e:
        conn.rollback()
        return False, str(e), [], []
    finally:
        conn.close()

def log_spy_permission_change(target_ext, added_exts, removed_exts, username=""):
    if not added_exts and not removed_exts:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO spy_audit_log
        (event_type, target_ext, added_exts, removed_exts, username)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "permission_change",
        str(target_ext),
        ",".join(str(x) for x in added_exts),
        ",".join(str(x) for x in removed_exts),
        str(username or "")
    ))
    conn.commit()
    conn.close()

def log_spy_attempt(caller_ext, target_ext, mode, result, reason="", username=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO spy_audit_log
        (event_type, target_ext, caller_ext, mode, result, reason, username)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "attempt",
        str(target_ext or ""),
        str(caller_ext or ""),
        str(mode or ""),
        str(result or ""),
        str(reason or ""),
        str(username or "")
    ))
    conn.commit()
    conn.close()

def add_extension(data):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO extensions 
            (ext, enabled, name, callerid_number, secret, max_contacts, max_expiration, ring_time, vm_enabled, vm_password, record_mode, dtmf_mode, moh_class, video_support, direct_media, nat, codecs, followme_json, mobile, allow_spy, email, sync_ldap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data["ext"], data["enabled"], data["name"], data["callerid_number"], data["secret"],
            data["max_contacts"], data["max_expiration"], data["ring_time"], data["vm_enabled"],
            data["vm_password"], data["record_mode"], data.get("dtmf_mode", "rfc4733"), data.get("moh_class", "default"), int(data.get("video_support", 0) or 0), data["direct_media"], data["nat"],
            data.get("codecs", "alaw,ulaw"), json.dumps(data.get("followme", [])), data.get("mobile", ""),
            data.get("allow_spy", 1), data.get("email", ""), data.get("sync_ldap", 1)
        ))
        data["_web_password_once"] = _create_extension_web_user(
            cursor, data["ext"], data.get("email", ""), data.get("web_password")
        )
        conn.commit()
        return True
    except (sqlite3.IntegrityError, ValueError):
        conn.rollback()
        return False
    finally:
        conn.close()

def update_extension(ext, data):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE extensions SET
            enabled = ?, name = ?, callerid_number = ?, secret = ?, max_contacts = ?, 
            max_expiration = ?, ring_time = ?, vm_enabled = ?, vm_password = ?, 
            record_mode = ?, dtmf_mode = ?, moh_class = ?, video_support = ?, direct_media = ?, nat = ?, codecs = ?, followme_json = ?, mobile = ?,
            allow_spy = ?, email = ?, sync_ldap = ?
        WHERE ext = ?
    ''', (
        data["enabled"], data["name"], data["callerid_number"], data["secret"],
        data["max_contacts"], data["max_expiration"], data["ring_time"], data["vm_enabled"],
        data["vm_password"], data["record_mode"], data.get("dtmf_mode", "rfc4733"), data.get("moh_class", "default"), int(data.get("video_support", 0) or 0), data["direct_media"], data["nat"],
        data.get("codecs", "alaw,ulaw"), json.dumps(data.get("followme", [])), data.get("mobile", ""),
        data.get("allow_spy", 1), data.get("email", ""), data.get("sync_ldap", 1), ext
    ))
    conn.commit()
    conn.close()

def update_extension_self_service(ext, values):
    """Update only fields exposed by the extension employee portal."""
    allowed = {
        "name", "email", "mobile", "secret", "ring_time",
        "vm_enabled", "vm_password"
    }
    fields = []
    params = []
    for key in allowed:
        if key in values:
            fields.append(f"{key} = ?")
            params.append(values[key])
    if not fields:
        return True, ""

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        params.append(str(ext))
        cursor.execute(f"UPDATE extensions SET {', '.join(fields)} WHERE ext = ?", params)
        if cursor.rowcount != 1:
            raise ValueError("Extension not found.")
        if "email" in values:
            cursor.execute("""
                UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_type = 'extension_user' AND extension_ext = ?
            """, (values["email"], str(ext)))
            if cursor.rowcount != 1:
                raise ValueError("Linked Extension Web User not found.")
        conn.commit()
        return True, ""
    except Exception as exc:
        conn.rollback()
        return False, str(exc)
    finally:
        conn.close()

def delete_extension(ext):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        cursor.execute("DELETE FROM extension_spy_permissions WHERE target_ext = ? OR allowed_ext = ?", (ext, ext))
        cursor.execute("DELETE FROM users WHERE user_type = 'extension_user' AND extension_ext = ?", (str(ext),))
        if cursor.rowcount != 1:
            raise ValueError(f"Linked Web User for extension {ext} was not found.")
        cursor.execute("DELETE FROM extensions WHERE ext = ?", (str(ext),))
        if cursor.rowcount != 1:
            raise ValueError(f"Extension {ext} was not found.")
        conn.commit()
        cleanup_reporting_scope_references("extensions", ext)
        return True, ""
    except Exception as exc:
        conn.rollback()
        return False, str(exc)
    finally:
        conn.close()

def get_extension_calls(ext, search="", date_from="", date_to="", status="",
                        direction="", sort_by="start_time", sort_order="desc",
                        page=1, per_page=20):
    ext = str(ext)
    clauses = ["(c.src = ? OR c.dst = ?)"]
    params = [ext, ext]
    if search:
        clauses.append("(c.src LIKE ? OR c.dst LIKE ? OR c.clid LIKE ?)")
        token = f"%{search}%"
        params.extend([token, token, token])
    if date_from:
        clauses.append("c.start_time >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        clauses.append("c.start_time <= ?")
        params.append(f"{date_to} 23:59:59")
    if status:
        clauses.append("UPPER(c.status) = ?")
        params.append(str(status).upper())
    if direction == "incoming":
        clauses.append("c.dst = ? AND c.src != ?")
        params.extend([ext, ext])
    elif direction == "outgoing":
        clauses.append("c.src = ? AND c.dst != ?")
        params.extend([ext, ext])
    elif direction == "internal":
        clauses.append("EXISTS (SELECT 1 FROM extensions e WHERE e.ext = CASE WHEN c.src = ? THEN c.dst ELSE c.src END)")
        params.append(ext)
    elif direction == "external":
        clauses.append("NOT EXISTS (SELECT 1 FROM extensions e WHERE e.ext = CASE WHEN c.src = ? THEN c.dst ELSE c.src END)")
        params.append(ext)

    sort_columns = {
        "date": "c.start_time", "start_time": "c.start_time", "number": "other_number",
        "duration": "c.billsec", "status": "c.status", "direction": "direction"
    }
    order_column = sort_columns.get(sort_by, "c.start_time")
    order_direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
    page = max(1, int(page or 1))
    per_page = min(100, max(10, int(per_page or 20)))
    where_sql = " AND ".join(clauses)
    select_sql = """
        SELECT c.*,
               CASE WHEN c.src = ? THEN 'outgoing' ELSE 'incoming' END AS direction,
               CASE WHEN c.src = ? THEN c.dst ELSE c.src END AS other_number,
               CASE WHEN EXISTS (
                    SELECT 1 FROM extensions e
                    WHERE e.ext = CASE WHEN c.src = ? THEN c.dst ELSE c.src END
               ) THEN 'internal' ELSE 'external' END AS call_type
        FROM cdr_records c
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM cdr_records c WHERE {where_sql}", params)
    total = cursor.fetchone()[0]
    data_params = [ext, ext, ext] + params + [per_page, (page - 1) * per_page]
    cursor.execute(
        f"{select_sql} WHERE {where_sql} ORDER BY {order_column} {order_direction} LIMIT ? OFFSET ?",
        data_params
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows, total

def get_extension_today_stats(ext):
    ext = str(ext)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN UPPER(status) = 'ANSWERED' THEN 1 ELSE 0 END) AS answered,
            SUM(CASE WHEN UPPER(status) IN ('NO ANSWER', 'NOANSWER', 'MISSED') THEN 1 ELSE 0 END) AS missed,
            SUM(CASE WHEN dst = ? THEN 1 ELSE 0 END) AS incoming,
            SUM(CASE WHEN src = ? THEN 1 ELSE 0 END) AS outgoing,
            COALESCE(SUM(billsec), 0) AS talk_time
        FROM cdr_records
        WHERE (src = ? OR dst = ?) AND date(start_time) = date('now', 'localtime')
    """, (ext, ext, ext, ext))
    row = dict(cursor.fetchone())
    conn.close()
    return {key: (value or 0) for key, value in row.items()}

# Trunk Database Helpers
def get_all_trunks():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trunks ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_trunk(name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trunks WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def add_trunk(data):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO trunks 
            (name, enabled, type, register_mode, server_addr, server_port, keepalive, transport, 
             outproxy_addr, outproxy_port, password, username, auth_id, from_user, from_domain, identify_by,
             context, codecs, allowed_ip, caller_id, qualify, nat, max_expiration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data["name"], data["enabled"], data["type"], data["register_mode"], data["server_addr"],
            data["server_port"], data["keepalive"], data["transport"], data["outproxy_addr"],
            data["outproxy_port"], data["password"], data["username"], data["auth_id"],
            data["from_user"], data["from_domain"], data["identify_by"],
            data.get("context", "from-trunk"), data.get("codecs", "ulaw,alaw"), data.get("allowed_ip", ""),
            data.get("caller_id", ""), data.get("qualify", 1), data.get("nat", 0), data.get("max_expiration", 3600)
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_trunk(name, data):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trunks SET
            enabled = ?, type = ?, register_mode = ?, server_addr = ?, server_port = ?, 
            keepalive = ?, transport = ?, outproxy_addr = ?, outproxy_port = ?, 
            password = ?, username = ?, auth_id = ?, from_user = ?, from_domain = ?, identify_by = ?,
            context = ?, codecs = ?, allowed_ip = ?, caller_id = ?, qualify = ?, nat = ?, max_expiration = ?
        WHERE name = ?
    ''', (
        data["enabled"], data["type"], data["register_mode"], data["server_addr"], data["server_port"],
        data["keepalive"], data["transport"], data["outproxy_addr"], data["outproxy_port"],
        data["password"], data["username"], data["auth_id"], data["from_user"], data["from_domain"],
        data["identify_by"], data.get("context", "from-trunk"), data.get("codecs", "ulaw,alaw"),
        data.get("allowed_ip", ""), data.get("caller_id", ""), data.get("qualify", 1),
        data.get("nat", 0), data.get("max_expiration", 3600), name
    ))
    conn.commit()
    conn.close()

def delete_trunk(name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM trunk_dods WHERE trunk_id = ?", (name,))
    trunk_dod_ids = [row["id"] for row in cursor.fetchall()]
    if trunk_dod_ids:
        placeholders = ",".join(["?"] * len(trunk_dod_ids))
        cursor.execute(f"DELETE FROM trunk_dod_extensions WHERE trunk_dod_id IN ({placeholders})", trunk_dod_ids)
        cursor.execute(f"DELETE FROM trunk_dods WHERE id IN ({placeholders})", trunk_dod_ids)
    cursor.execute("DELETE FROM trunks WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def _dedupe_keep_order(values):
    seen = set()
    result = []
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def _fetch_dods(conn, table_name, ext_table_name, parent_col, parent_value):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name} WHERE {parent_col} = ? ORDER BY id", (parent_value,))
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        cursor.execute(f"SELECT extension_id FROM {ext_table_name} WHERE {table_name[:-1]}_id = ? ORDER BY id", (row["id"],))
        row["extensions"] = [ext_row["extension_id"] for ext_row in cursor.fetchall()]
    return rows

def _save_dod_record(table_name, ext_table_name, parent_col, parent_value, dod_id, dod_number, dod_name, extension_ids):
    conn = get_db()
    cursor = conn.cursor()
    extension_ids = _dedupe_keep_order(extension_ids)
    try:
        if dod_id:
            cursor.execute(
                f"SELECT id FROM {table_name} WHERE {parent_col} = ? AND dod_number = ? AND id != ?",
                (parent_value, dod_number, dod_id)
            )
        else:
            cursor.execute(
                f"SELECT id FROM {table_name} WHERE {parent_col} = ? AND dod_number = ?",
                (parent_value, dod_number)
            )
        if cursor.fetchone():
            return False

        if dod_id:
            cursor.execute(
                f"UPDATE {table_name} SET dod_number = ?, dod_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND {parent_col} = ?",
                (dod_number, dod_name, dod_id, parent_value)
            )
        else:
            cursor.execute(
                f"INSERT INTO {table_name} ({parent_col}, dod_number, dod_name) VALUES (?, ?, ?)",
                (parent_value, dod_number, dod_name)
            )
            dod_id = cursor.lastrowid

        if cursor.rowcount == 0:
            conn.rollback()
            return False

        cursor.execute(f"DELETE FROM {ext_table_name} WHERE {table_name[:-1]}_id = ?", (dod_id,))
        for ext_id in extension_ids:
            cursor.execute(
                f"INSERT INTO {ext_table_name} ({table_name[:-1]}_id, extension_id) VALUES (?, ?)",
                (dod_id, ext_id)
            )

        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _delete_dod_record(table_name, ext_table_name, dod_id, parent_col=None, parent_value=None):
    conn = get_db()
    cursor = conn.cursor()
    try:
        if parent_col is not None:
            cursor.execute(
                f"SELECT id FROM {table_name} WHERE id = ? AND {parent_col} = ?",
                (dod_id, parent_value)
            )
        else:
            cursor.execute(f"SELECT id FROM {table_name} WHERE id = ?", (dod_id,))
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute(f"DELETE FROM {ext_table_name} WHERE {table_name[:-1]}_id = ?", (dod_id,))
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (dod_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_trunk_dods(trunk_id):
    conn = get_db()
    try:
        return _fetch_dods(conn, "trunk_dods", "trunk_dod_extensions", "trunk_id", trunk_id)
    finally:
        conn.close()

def get_trunk_dod(trunk_id, dod_id):
    dods = get_trunk_dods(trunk_id)
    return next((row for row in dods if str(row.get("id")) == str(dod_id)), None)

def save_trunk_dod(trunk_id, dod_id, dod_number, dod_name, extension_ids):
    return _save_dod_record("trunk_dods", "trunk_dod_extensions", "trunk_id", trunk_id, dod_id, dod_number, dod_name, extension_ids)

def delete_trunk_dod(trunk_id, dod_id):
    return _delete_dod_record("trunk_dods", "trunk_dod_extensions", dod_id, "trunk_id", trunk_id)

def delete_trunk_dods_for_trunk(trunk_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM trunk_dods WHERE trunk_id = ?", (trunk_id,))
        dod_ids = [row["id"] for row in cursor.fetchall()]
        if dod_ids:
            placeholders = ",".join(["?"] * len(dod_ids))
            cursor.execute(f"DELETE FROM trunk_dod_extensions WHERE trunk_dod_id IN ({placeholders})", dod_ids)
            cursor.execute(f"DELETE FROM trunk_dods WHERE id IN ({placeholders})", dod_ids)
        conn.commit()
    finally:
        conn.close()

def get_outbound_route_dods(route_id):
    conn = get_db()
    try:
        return _fetch_dods(conn, "outbound_route_dods", "outbound_route_dod_extensions", "outbound_route_id", route_id)
    finally:
        conn.close()

def get_outbound_route_dod(route_id, dod_id):
    dods = get_outbound_route_dods(route_id)
    return next((row for row in dods if str(row.get("id")) == str(dod_id)), None)

def save_outbound_route_dod(route_id, dod_id, dod_number, dod_name, extension_ids):
    return _save_dod_record("outbound_route_dods", "outbound_route_dod_extensions", "outbound_route_id", route_id, dod_id, dod_number, dod_name, extension_ids)

def delete_outbound_route_dod(route_id, dod_id):
    return _delete_dod_record("outbound_route_dods", "outbound_route_dod_extensions", dod_id, "outbound_route_id", route_id)

def delete_outbound_route_dods_for_route(route_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM outbound_route_dods WHERE outbound_route_id = ?", (route_id,))
        dod_ids = [row["id"] for row in cursor.fetchall()]
        if dod_ids:
            placeholders = ",".join(["?"] * len(dod_ids))
            cursor.execute(f"DELETE FROM outbound_route_dod_extensions WHERE outbound_route_dod_id IN ({placeholders})", dod_ids)
            cursor.execute(f"DELETE FROM outbound_route_dods WHERE id IN ({placeholders})", dod_ids)
        conn.commit()
    finally:
        conn.close()

# User login authentication with adaptive hash check and transparent migration
def _password_matches_hash(stored_hash, password):
    stored_hash = str(stored_hash or "")
    if len(stored_hash) == 64 and all(c in '0123456789abcdefABCDEF' for c in stored_hash):
        return stored_hash == hashlib.sha256(str(password).encode('utf-8')).hexdigest()
    try:
        return check_password_hash(stored_hash, str(password))
    except (ValueError, TypeError):
        return False

def authenticate_user(username, password):
    user = get_user_by_username(username)
    if not user or user.get('status', 'enabled') != 'enabled':
        return False
    stored_hash = user['password']
    if not _password_matches_hash(stored_hash, password):
        return False
    if len(stored_hash) == 64 and all(c in '0123456789abcdefABCDEF' for c in stored_hash):
        try:
            update_user_password(username, generate_password_hash(password))
        except Exception as exc:
            print(f"Server log: Failed to rehash password for {username}: {exc}")
    return True

def record_user_login(user_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT last_login_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        previous = row["last_login_at"]
        cursor.execute("""
            UPDATE users
            SET previous_login_at = last_login_at,
                last_login_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user_id,))
        conn.commit()
        return previous
    finally:
        conn.close()

def update_admin_password(new_password):
    conn = get_db()
    cursor = conn.cursor()
    if not (new_password.startswith('pbkdf2:') or new_password.startswith('scrypt:')):
        hashed = generate_password_hash(new_password)
    else:
        hashed = new_password
    cursor.execute("UPDATE users SET password = ?, session_version = COALESCE(session_version, 1) + 1 WHERE username = 'admin'", (hashed,))
    conn.commit()
    conn.close()

# --- Call Routing & Media Center JSON Database Helpers ---
IVR_FILE = "/etc/asterisk/rcm_ivrs.json"
RG_FILE = "/etc/asterisk/rcm_ring_groups.json"
PAGING_FILE = "/etc/asterisk/rcm_paging_intercom.json"
QUEUE_FILE = "/etc/asterisk/rcm_queues.json"
SD_FILE = "/etc/asterisk/rcm_speed_dials.json"
FC_FILE = "/etc/asterisk/rcm_feature_codes.json"
PG_FILE = "/etc/asterisk/rcm_pickup_groups.json"
ANN_FILE = "/etc/asterisk/rcm_announcements.json"
MC_FILE = "/etc/asterisk/rcm_media_center.json"

def _load_json_db(file_path, default_data):
    if not os.path.exists(file_path):
        return default_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_data

def _save_json_db(file_path, data):
    try:
        dir_name = os.path.dirname(file_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

def get_ivrs():
    return _load_json_db(IVR_FILE, {"ivrs": []}).get("ivrs", [])
def save_ivrs(ivrs):
    exts = {str(e.get("ext")).strip() for e in get_all_extensions() if e.get("ext")}
    for ivr in ivrs:
        keys = [str(m.get("key")).strip() for m in ivr.get("mappings", []) if m.get("key")]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate DTMF options are not allowed within the same IVR context.")
        ultra_numbers = [
            str(m.get("number") or "").strip()
            for m in ivr.get("ultra_numbers", [])
            if str(m.get("number") or "").strip()
        ]
        if len(ultra_numbers) != len(set(ultra_numbers)):
            raise ValueError("Duplicate Ultra Number options are not allowed within the same IVR context.")
        for u_num in ultra_numbers:
            if u_num in keys:
                raise ValueError(f"Ultra Number '{u_num}' conflicts with DTMF keypad option '{u_num}' within the same IVR.")
            if u_num in exts:
                raise ValueError(f"Ultra Number '{u_num}' is already used by an existing internal extension.")
    return _save_json_db(IVR_FILE, {"ivrs": ivrs})

def get_ring_groups():
    data = _load_json_db(RG_FILE, {"groups": []})
    if isinstance(data, list):
        return data
    return data.get("groups", [])
def save_ring_groups(groups):
    old_ids = {
        str(group.get("id") or group.get("group_id") or "").strip()
        for group in get_ring_groups()
        if str(group.get("id") or group.get("group_id") or "").strip()
    }
    result = _save_json_db(RG_FILE, {"groups": groups})
    if result:
        new_ids = {
            str(group.get("id") or group.get("group_id") or "").strip()
            for group in groups or []
            if str(group.get("id") or group.get("group_id") or "").strip()
        }
        for group_id in old_ids - new_ids:
            cleanup_reporting_scope_references("ring_groups", group_id)
    return result

def get_paging():
    data = _load_json_db(PAGING_FILE, {"items": []})
    return data.get("items", [])
def save_paging(items):
    return _save_json_db(PAGING_FILE, {"items": items})

def get_queues():
    data = _load_json_db(QUEUE_FILE, {"queues": []})
    return data.get("queues", [])
def save_queues(queues):
    old_ids = {
        str(queue.get("queue_number") or "").strip()
        for queue in get_queues()
        if str(queue.get("queue_number") or "").strip()
    }
    res = _save_json_db(QUEUE_FILE, {"queues": queues})
    if res:
        new_ids = {
            str(queue.get("queue_number") or "").strip()
            for queue in queues or []
            if str(queue.get("queue_number") or "").strip()
        }
        for queue_id in old_ids - new_ids:
            cleanup_reporting_scope_references("queues", queue_id)
    try:
        import rcm_queue_db
        # Sync all queues to SQLite queues table
        for q in queues:
            q_num = q.get("queue_number", "").strip()
            name = q.get("name", "").strip()
            strategy = q.get("strategy", "rrmemory")
            max_members = int(q.get("max_queue_length", 0) or 0)
            timeout = int(q.get("ring_time", 0) or 0)
            retry = int(q.get("retry_time", 0) or 0)
            servicelevel = int(q.get("servicelevel", 30) or 30)
            rcm_queue_db.db_sync_queue(q_num, name, strategy, max_members, timeout, retry, servicelevel)
            
        # Prune deleted queues
        active_numbers = [q.get("queue_number", "").strip() for q in queues if q.get("queue_number")]
        conn = rcm_queue_db.get_db_connection()
        c = conn.cursor()
        if active_numbers:
            placeholders = ",".join(["?"] * len(active_numbers))
            c.execute(f"DELETE FROM queues WHERE queue_number NOT IN ({placeholders})", active_numbers)
        else:
            c.execute("DELETE FROM queues")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error syncing queues to SQLite DB: {e}")
    return res

def get_speed_dials():
    return _load_json_db(SD_FILE, {"speed_dials": []}).get("speed_dials", [])
def save_speed_dials(speed_dials):
    return _save_json_db(SD_FILE, {"speed_dials": speed_dials})

def get_all_feature_codes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_feature_codes ORDER BY feature_category, id")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_feature_by_name(name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_feature_codes WHERE feature_name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_role(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.role, u.legacy_role, p.legacy_role AS priv_legacy
        FROM users u
        LEFT JOIN privileges p ON u.privilege_id = p.id
        WHERE u.username = ?
    """, (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row["priv_legacy"] or row["legacy_role"] or row["role"] or "agent"
    return "agent"

def update_feature_code(feature_id, code, enabled, description, permissions, destination_number="", timeout=15):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE rcm_feature_codes
        SET feature_code = ?,
            enabled = ?,
            description = ?,
            permissions = ?,
            destination_number = ?,
            timeout = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (code, enabled, description, permissions, destination_number, timeout, feature_id))
    conn.commit()
    conn.close()

def get_feature_codes():
    # Backward compatibility: mapping DB rows to old dict representation
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT feature_name, feature_code FROM rcm_feature_codes WHERE enabled = 1")
    rows = cursor.fetchall()
    conn.close()
    
    mapping = {
        "My Voicemail": "vm",
        "Forward Busy Activate": "fwd_busy_on",
        "Forward Busy Deactivate": "fwd_busy_off",
        "Forward No Answer Activate": "fwd_noans_on",
        "Forward No Answer Deactivate": "fwd_noans_off",
        "Forward Always Activate": "fwd_always_on",
        "Forward Always Deactivate": "fwd_always_off",
        "DND Activate": "dnd_on",
        "DND Deactivate": "dnd_off",
        "General Call Pickup": "pickup",
        "Direct Call Pickup": "directed_pickup"
    }
    
    result = {}
    for r in rows:
        name = r["feature_name"]
        code = r["feature_code"]
        if name in mapping:
            result[mapping[name]] = code
    return result

def save_feature_codes(fc):
    conn = get_db()
    cursor = conn.cursor()
    mapping = {
        "vm": "My Voicemail",
        "fwd_busy_on": "Forward Busy Activate",
        "fwd_busy_off": "Forward Busy Deactivate",
        "fwd_noans_on": "Forward No Answer Activate",
        "fwd_noans_off": "Forward No Answer Deactivate",
        "fwd_always_on": "Forward Always Activate",
        "fwd_always_off": "Forward Always Deactivate",
        "dnd_on": "DND Activate",
        "dnd_off": "DND Deactivate",
        "pickup": "General Call Pickup",
        "directed_pickup": "Direct Call Pickup"
    }
    for key, val in fc.items():
        if key in mapping:
            cursor.execute("""
                UPDATE rcm_feature_codes
                SET feature_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE feature_name = ?
            """, (val, mapping[key]))
    conn.commit()
    conn.close()
    return _save_json_db(FC_FILE, fc)

def get_pickup_groups():
    return _load_json_db(PG_FILE, {"pickup_groups": []}).get("pickup_groups", [])
def save_pickup_groups(groups):
    return _save_json_db(PG_FILE, {"pickup_groups": groups})

def get_announcements():
    return _load_json_db(ANN_FILE, {"announcements": []}).get("announcements", [])
def save_announcements(announcements):
    return _save_json_db(ANN_FILE, {"announcements": announcements})

def get_media_center_db():
    return _load_json_db(MC_FILE, {"prompts": [], "moh_classes": []})
def save_media_center_db(db):
    return _save_json_db(MC_FILE, db)

TIME_FILE = "/etc/asterisk/rcm_time_settings.json"
NETWORK_FILE = "/etc/asterisk/rcm_network_settings.json"
PBX_SETTINGS_FILE = "/etc/asterisk/rcm_pbx_settings.json"
PBX_OPERATION_LOG_FILE = "/etc/asterisk/rcm_pbx_operation_log.json"

def get_time_settings():
    default_time = {
        "mode": "automatic",
        "ntp_server": "pool.ntp.org",
        "timezone": "Africa/Cairo",
        "ntp_server_enabled": False
    }
    return _load_json_db(TIME_FILE, default_time)

def save_time_settings(data):
    return _save_json_db(TIME_FILE, data)

def get_network_settings():
    default_network = {
        "mode": "dhcp",
        "ip_address": "",
        "subnet_mask": "",
        "gateway": "",
        "dns1": "",
        "dns2": ""
    }
    return _load_json_db(NETWORK_FILE, default_network)

def save_network_settings(data):
    return _save_json_db(NETWORK_FILE, data)

def get_default_pbx_settings():
    return {
        "extension_defaults": {
            "dtmf_mode": "rfc4733",
            "blind_transfer_timeout": 15,
            "ring_time": 60,
            "moh_class": "default",
            "video_support": False
        },
        "sip_settings": {},
        "global_settings": {
            "max_concurrent_calls": 0
        }
    }

def get_pbx_settings():
    defaults = get_default_pbx_settings()
    data = _load_json_db(PBX_SETTINGS_FILE, defaults)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("extension_defaults", {})
    data.setdefault("sip_settings", {})
    data.setdefault("global_settings", {})
    for key, value in defaults["extension_defaults"].items():
        data["extension_defaults"].setdefault(key, value)
    for key, value in defaults["global_settings"].items():
        data["global_settings"].setdefault(key, value)
    return data

def save_pbx_settings(data):
    current = get_pbx_settings()
    if isinstance(data, dict):
        if isinstance(data.get("extension_defaults"), dict):
            current["extension_defaults"].update(data["extension_defaults"])
        if isinstance(data.get("sip_settings"), dict):
            current["sip_settings"].update(data["sip_settings"])
        if isinstance(data.get("global_settings"), dict):
            current["global_settings"].update(data["global_settings"])
    return _save_json_db(PBX_SETTINGS_FILE, current)

def _flatten_settings(data, prefix=""):
    flat = {}
    if not isinstance(data, dict):
        return flat
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_settings(value, path))
        else:
            flat[path] = value
    return flat

def diff_pbx_settings(before, after):
    old_flat = _flatten_settings(before)
    new_flat = _flatten_settings(after)
    changes = []
    for key in sorted(set(old_flat) | set(new_flat)):
        old_value = old_flat.get(key)
        new_value = new_flat.get(key)
        if old_value != new_value:
            changes.append({
                "setting": key,
                "old": old_value,
                "new": new_value
            })
    return changes

def log_pbx_settings_change(before, after, username="", ip_address=""):
    changes = diff_pbx_settings(before, after)
    if not changes:
        return False
    return log_pbx_operation(
        module="PBX Settings",
        action="PBX Settings Updated",
        username=username,
        ip_address=ip_address,
        result="Success",
        changes=changes
    )

SENSITIVE_LOG_KEYWORDS = ("password", "secret", "token", "cookie", "hash", "otp", "pin", "auth_id", "api_key", "voicemail pin", "sip password")

def _sanitize_log_changes(changes):
    if not changes or not isinstance(changes, list):
        return []
    sanitized = []
    for c in changes:
        if isinstance(c, dict):
            setting = str(c.get("setting", ""))
            if any(word in setting.lower() for word in SENSITIVE_LOG_KEYWORDS):
                sanitized.append({"setting": setting, "old": "******", "new": "******"})
            else:
                sanitized.append(c)
        else:
            sanitized.append(c)
    return sanitized

def log_pbx_operation(action="PBX Operation", username="", ip_address="", status="", message="", changes=None, module="PBX Settings", details="", result=""):
    data = _load_json_db(PBX_OPERATION_LOG_FILE, {"logs": []})
    if not isinstance(data, dict):
        data = {"logs": []}
    logs = data.get("logs", [])
    if not isinstance(logs, list):
        logs = []
    final_result = str(result or status or "Success")
    final_details = str(details or message or "")
    logs.insert(0, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "username": str(username or ""),
        "user": str(username or ""),
        "module": str(module or "PBX Settings"),
        "ip_address": str(ip_address or ""),
        "ip": str(ip_address or ""),
        "action": str(action or "PBX Operation"),
        "status": final_result.lower(),
        "result": final_result,
        "message": final_details,
        "details": final_details,
        "changes": _sanitize_log_changes(changes)
    })
    data["logs"] = logs[:1000]
    return _save_json_db(PBX_OPERATION_LOG_FILE, data)

def get_pbx_operation_logs(limit=200, module="", action="", result="", search=""):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 1000))
    data = _load_json_db(PBX_OPERATION_LOG_FILE, {"logs": []})
    logs = data.get("logs", []) if isinstance(data, dict) else []
    if not isinstance(logs, list):
        return []
    module = str(module or "").strip().lower()
    action = str(action or "").strip().lower()
    result = str(result or "").strip().lower()
    search = str(search or "").strip().lower()
    filtered = []
    for log in logs:
        if not isinstance(log, dict):
            continue
        log_module = str(log.get("module") or "PBX Settings")
        log_action = str(log.get("action") or "")
        log_result = str(log.get("result") or log.get("status") or "")
        haystack = " ".join([
            str(log.get("timestamp") or ""),
            str(log.get("username") or log.get("user") or ""),
            log_module,
            log_action,
            str(log.get("details") or log.get("message") or ""),
            str(log.get("ip_address") or log.get("ip") or ""),
            log_result,
        ]).lower()
        if module and log_module.lower() != module:
            continue
        if action and action not in log_action.lower():
            continue
        if result and log_result.lower() != result:
            continue
        if search:
            # Smart Search: all words must be present in the haystack
            words = search.split()
            match = True
            for w in words:
                if w not in haystack:
                    match = False
                    break
            if not match:
                continue
                
        filtered.append(log)
        if len(filtered) >= limit:
            break
    return filtered

def get_pbx_operation_log_facets():
    data = _load_json_db(PBX_OPERATION_LOG_FILE, {"logs": []})
    logs = data.get("logs", []) if isinstance(data, dict) else []
    if not isinstance(logs, list):
        return {"modules": [], "results": []}
    modules = sorted({str(log.get("module") or "PBX Settings") for log in logs if isinstance(log, dict)})
    results = sorted({str(log.get("result") or log.get("status") or "Success") for log in logs if isinstance(log, dict)})
    return {"modules": modules, "results": results}

ROUTES_FILE = "/etc/asterisk/rcm_outbound/routes.json"
LEGACY_ROUTES_FILE = "/etc/asterisk/rcm_outbound_routes.json"

def get_outbound_routes():
    data = _load_json_db(ROUTES_FILE, {"routes": []})
    if not data or not data.get("routes"):
        data = _load_json_db(LEGACY_ROUTES_FILE, {"routes": []})
    if isinstance(data, list):
        return data
    return data.get("routes", [])

def save_outbound_routes(routes):
    data = {"routes": routes}
    _save_json_db(ROUTES_FILE, data)
    return _save_json_db(LEGACY_ROUTES_FILE, data)

OFFICE_TIMES_FILE = "/etc/asterisk/rcm_office_times.json"
HOLIDAYS_FILE = "/etc/asterisk/rcm_holidays.json"
INBOUND_ROUTES_FILE = "/etc/asterisk/rcm_inbound_routes.json"

def get_office_time_classes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM office_time_classes ORDER BY name")
    classes = [dict(row) for row in cursor.fetchall()]
    
    day_order = {
        "sunday": 0,
        "monday": 1,
        "tuesday": 2,
        "wednesday": 3,
        "thursday": 4,
        "friday": 5,
        "saturday": 6
    }
    
    for c in classes:
        cursor.execute("SELECT * FROM office_time_rules WHERE class_id = ?", (c["id"],))
        rules = [dict(row) for row in cursor.fetchall()]
        rules.sort(key=lambda r: (day_order.get(r.get("day_of_week", "").lower(), 99), r.get("start_time", "")))
        c["rules"] = rules
        
    conn.close()
    return classes

def get_office_time_class(class_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM office_time_classes WHERE id = ?", (class_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    c = dict(row)
    cursor.execute("SELECT * FROM office_time_rules WHERE class_id = ?", (class_id,))
    c["rules"] = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return c

def save_office_time_class(class_id, name, description, enabled, rules):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO office_time_classes (id, name, description, enabled) VALUES (?, ?, ?, ?)",
                       (class_id, name, description, 1 if enabled else 0))
        cursor.execute("DELETE FROM office_time_rules WHERE class_id = ?", (class_id,))
        for r in rules:
            cursor.execute("INSERT INTO office_time_rules (class_id, day_of_week, start_time, end_time) VALUES (?, ?, ?, ?)",
                           (class_id, r.get("day_of_week"), r.get("start_time"), r.get("end_time")))
        conn.commit()
        success = True
    except Exception as e:
        print(f"Error saving office time class: {e}")
        conn.rollback()
        success = False
    finally:
        conn.close()
    return success

def delete_office_time_class(class_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM office_time_classes WHERE id = ?", (class_id,))
        conn.commit()
        success = True
    except Exception as e:
        print(f"Error deleting office time class: {e}")
        conn.rollback()
        success = False
    finally:
        conn.close()
    return success

def toggle_office_time_class(class_id, enabled):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE office_time_classes SET enabled = ? WHERE id = ?", (1 if enabled else 0, class_id))
        conn.commit()
        success = True
    except Exception as e:
        print(f"Error toggling office time class: {e}")
        conn.rollback()
        success = False
    finally:
        conn.close()
    return success

def clone_office_time_class(class_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM office_time_classes WHERE id = ?", (class_id,))
        orig = cursor.fetchone()
        if not orig:
            conn.close()
            return False
            
        import uuid
        new_id = str(uuid.uuid4())[:8]
        new_name = orig["name"] + "_copy"
        
        cursor.execute("SELECT COUNT(*) FROM office_time_classes WHERE name = ?", (new_name,))
        if cursor.fetchone()[0] > 0:
            new_name = orig["name"] + "_copy_" + new_id
            
        cursor.execute("INSERT INTO office_time_classes (id, name, description, enabled) VALUES (?, ?, ?, ?)",
                       (new_id, new_name, orig["description"], orig["enabled"]))
                       
        cursor.execute("SELECT * FROM office_time_rules WHERE class_id = ?", (class_id,))
        rules = cursor.fetchall()
        for r in rules:
            cursor.execute("INSERT INTO office_time_rules (class_id, day_of_week, start_time, end_time) VALUES (?, ?, ?, ?)",
                           (new_id, r["day_of_week"], r["start_time"], r["end_time"]))
        conn.commit()
        success = True
    except Exception as e:
        print(f"Error cloning office time class: {e}")
        conn.rollback()
        success = False
    finally:
        conn.close()
    return success

def get_office_times():
    return get_office_time_classes()

def get_holidays():
    return _load_json_db(HOLIDAYS_FILE, {"holidays": []}).get("holidays", [])

def save_holidays(holidays):
    return _save_json_db(HOLIDAYS_FILE, {"holidays": holidays})

def _normalize_inbound_did_pattern(pattern):
    pattern = str(pattern or "").strip()
    if not pattern:
        return ""
    if pattern in {"s", "i", "t", "h"}:
        return pattern
    if pattern.startswith("_"):
        body = pattern[1:]
        body = body.replace("x", "X").replace("n", "N").replace("z", "Z")
        return f"_{body}"
    if pattern.isdigit():
        return pattern
    if re.search(r"[xXnNzZ\.\[\]\-\*]", pattern):
        body = pattern.replace("x", "X").replace("n", "N").replace("z", "Z")
        return f"_{body}"
    return pattern

def get_inbound_routes():
    inbound_routes = _load_json_db(INBOUND_ROUTES_FILE, {"inbound_routes": []}).get("inbound_routes", [])
    for route in inbound_routes:
        route.pop("priority", None)
        route["did_patterns"] = [_normalize_inbound_did_pattern(p) for p in route.get("did_patterns", []) if str(p).strip()]
        route["cid_pattern"] = _normalize_inbound_did_pattern(route.get("cid_pattern", ""))
    return inbound_routes

def save_inbound_routes(inbound_routes):
    normalized_routes = []
    for route in inbound_routes or []:
        route = dict(route or {})
        route.pop("priority", None)
        route["did_patterns"] = [_normalize_inbound_did_pattern(p) for p in route.get("did_patterns", []) if str(p).strip()]
        route["cid_pattern"] = _normalize_inbound_did_pattern(route.get("cid_pattern", ""))
        normalized_routes.append(route)
    return _save_json_db(INBOUND_ROUTES_FILE, {"inbound_routes": normalized_routes})

# --- Call Center Helpers ---

def get_filtered_queue_stats(filters):
    import rcm_queue_db
    return rcm_queue_db.get_filtered_queue_stats(filters)

def get_agent_analytics(filters):
    import rcm_queue_db
    return rcm_queue_db.get_agent_analytics(filters)

def get_queue_alerts():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_queue_alerts ORDER BY timestamp DESC LIMIT 50")
    alerts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return alerts

def add_queue_alert(queuename, alert_type, message):
    conn = get_db()
    cursor = conn.cursor()
    import time
    cursor.execute("SELECT id FROM rcm_queue_alerts WHERE queuename = ? AND alert_type = ? AND resolved = 0", (queuename, alert_type))
    row = cursor.fetchone()
    if row:
        alert_id = row["id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        cursor.execute("UPDATE rcm_queue_alerts SET timestamp = ?, message = ? WHERE id = ?", (int(time.time()), message, alert_id))
    else:
        cursor.execute("""
            INSERT INTO rcm_queue_alerts (timestamp, queuename, alert_type, message, resolved)
            VALUES (?, ?, ?, ?, 0)
        """, (int(time.time()), queuename, alert_type, message))
    conn.commit()
    conn.close()

def resolve_queue_alert(alert_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE rcm_queue_alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

def get_callback_requests():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_callback_requests ORDER BY timestamp DESC")
    callbacks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return callbacks

def add_callback_request(queuename, caller):
    conn = get_db()
    cursor = conn.cursor()
    import time
    cursor.execute("""
        INSERT INTO rcm_callback_requests (timestamp, queuename, caller, status)
        VALUES (?, ?, ?, 'pending')
    """, (int(time.time()), queuename, caller))
    conn.commit()
    conn.close()

def update_callback_status(callback_id, status, agent, notes):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE rcm_callback_requests 
        SET status = ?, agent = ?, notes = ? 
        WHERE id = ?
    """, (status, agent, notes, callback_id))
    conn.commit()
    conn.close()

def get_caller_lists():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rcm_caller_lists")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def add_caller_to_list(caller, list_type):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO rcm_caller_lists (caller, list_type) VALUES (?, ?)", (caller, list_type))
    conn.commit()
    conn.close()

def remove_caller_from_list(caller):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rcm_caller_lists WHERE caller = ?", (caller,))
    conn.commit()
    conn.close()

def seed_historical_queue_data():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM rcm_queue_calls")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return
        
    import random
    from datetime import datetime, timedelta
    
    cursor.execute("DELETE FROM rcm_queue_calls")
    cursor.execute("DELETE FROM rcm_agent_sessions")
    cursor.execute("DELETE FROM rcm_agent_pauses")
    cursor.execute("DELETE FROM rcm_queue_log")
    
    queues = [
        {"num": "6500", "name": "Support"},
        {"num": "6501", "name": "Sales"},
        {"num": "6502", "name": "Billing"}
    ]
    agents = [
        {"ext": "5001", "name": "Alice Smith"},
        {"ext": "5002", "name": "Bob Jones"},
        {"ext": "5003", "name": "Charlie Brown"},
        {"ext": "5004", "name": "David Davis"},
        {"ext": "5005", "name": "Eve Miller"},
        {"ext": "5006", "name": "Frank Wilson"},
        {"ext": "5007", "name": "Grace Lee"},
        {"ext": "5008", "name": "Henry Taylor"},
        {"ext": "5009", "name": "Ivy Thomas"},
        {"ext": "5010", "name": "Jack Jackson"}
    ]
    
    dispositions = ["Resolved", "Sales Lead", "Technical Issue", "Follow-up Required", "Spam / Hangup", "Billing Query"]
    trunks = ["Trunk-SIP-Main", "Trunk-SIP-Backup", "PSTN-Gateway"]
    pause_reasons = ["Lunch", "Break", "Meeting", "Training", "System Issue"]
    
    now = datetime.now()
    
    for day in range(30):
        date_current = now - timedelta(days=day)
        if date_current.weekday() >= 5 and random.random() > 0.3:
            continue
            
        active_agents = random.sample(agents, k=random.randint(5, 8))
        agent_day_sessions = []
        for ag in active_agents:
            q_assigned = random.choice(queues)["num"]
            start_hour = random.randint(8, 9)
            start_min = random.randint(0, 59)
            login_dt = datetime(date_current.year, date_current.month, date_current.day, start_hour, start_min)
            login_ts = int(login_dt.timestamp())
            
            end_hour = random.randint(16, 18)
            end_min = random.randint(0, 59)
            logout_dt = datetime(date_current.year, date_current.month, date_current.day, end_hour, end_min)
            logout_ts = int(logout_dt.timestamp())
            
            total_online = logout_ts - login_ts
            
            pause_time_total = 0
            lunch_start = login_ts + random.randint(3*3600, 5*3600)
            lunch_duration = random.randint(1800, 3600)
            cursor.execute("""
                INSERT INTO rcm_agent_pauses (agent, queuename, pause_time, unpause_time, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (ag["ext"], q_assigned, lunch_start, lunch_start + lunch_duration, "Lunch"))
            pause_time_total += lunch_duration
            
            if random.random() > 0.3:
                break_start = login_ts + random.randint(1*3600, 2*3600)
                break_dur = random.randint(300, 900)
                cursor.execute("""
                    INSERT INTO rcm_agent_pauses (agent, queuename, pause_time, unpause_time, reason)
                    VALUES (?, ?, ?, ?, ?)
                """, (ag["ext"], q_assigned, break_start, break_start + break_dur, random.choice(pause_reasons)))
                pause_time_total += break_dur
                
            avail_time = total_online - pause_time_total
            
            cursor.execute("""
                INSERT INTO rcm_agent_sessions (agent, queuename, login_time, logout_time, total_online_time, pause_time, available_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ag["ext"], q_assigned, login_ts, logout_ts, total_online, pause_time_total, avail_time))
            
            agent_day_sessions.append({"ext": ag["ext"], "q": q_assigned, "login": login_ts, "logout": logout_ts})
            
        num_calls = random.randint(40, 100)
        if date_current.weekday() in [0, 1]:
            num_calls = int(num_calls * 1.3)
            
        for _ in range(num_calls):
            h_pool = [8,9,10,10,11,11,11,12,12,13,14,14,15,15,15,16,16,17,18,19]
            h = random.choice(h_pool)
            m = random.randint(0, 59)
            s = random.randint(0, 59)
            call_dt = datetime(date_current.year, date_current.month, date_current.day, h, m, s)
            call_ts = int(call_dt.timestamp())
            
            callid = f"178{call_ts}.{random.randint(100, 999)}"
            q = random.choice(queues)
            qnum = q["num"]
            
            caller_num = "01" + "".join(str(random.randint(0, 9)) for _ in range(9))
            
            stat_roll = random.random()
            if stat_roll < 0.75:
                status = "ANSWERED"
                wait = random.randint(5, 60)
                talk = random.randint(30, 450)
                if random.random() > 0.9:
                    talk = random.randint(600, 1200)
                current_agents = [ag for ag in agent_day_sessions if ag["q"] == qnum and ag["login"] <= call_ts <= ag["logout"]]
                if current_agents:
                    agent_ext = random.choice(current_agents)["ext"]
                else:
                    agent_ext = random.choice(agents)["ext"]
                    
                hangup_by = random.choice(["agent", "caller"])
                disp = random.choice(dispositions)
                rec = f"q-{qnum}-{caller_num}-{call_dt.strftime('%Y%m%d-%H%M%S')}.wav"
            elif stat_roll < 0.93:
                status = "ABANDONED"
                wait = random.randint(10, 120)
                talk = 0
                agent_ext = ""
                hangup_by = "caller"
                disp = ""
                rec = ""
            else:
                status = random.choice(["TIMEOUT", "CANCELLED", "FAILED"])
                wait = random.randint(15, 90)
                talk = 0
                agent_ext = ""
                hangup_by = "caller"
                disp = ""
                rec = ""
                
            hold_time = random.randint(0, 15) if status == "ANSWERED" and random.random() > 0.6 else 0
            pos = random.randint(1, 4)
            trunk = random.choice(trunks)
            vip = 1 if random.random() > 0.95 else 0
            
            cursor.execute("""
                INSERT INTO rcm_queue_calls 
                (callid, queuename, caller, timestamp, status, agent, wait_time, talk_time, hold_time, position, hangup_by, recording_file, source_trunk, disposition_code, vip_priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                callid, qnum, caller_num, call_ts, status, agent_ext, wait, talk, hold_time, pos, hangup_by, rec, trunk, disp, vip
            ))
            
    # Seed some dummy raw log lines to complete the setup
    import time as pytime
    dummy_ts = int(pytime.time()) - 2*3600
    cursor.execute("""
        INSERT INTO rcm_queue_log (timestamp, callid, queuename, agent, event, arg1, arg2, arg3, arg4, arg5, processed)
        VALUES (?, 'NONE', '6500', '5001', 'ADDMEMBER', '', '', '', '', '', 1)
    """, (dummy_ts,))
    
    # Save queues list to rcm_queues.json if empty
    from db import get_queues, save_queues
    if not get_queues():
        save_queues([
            {"queue_number": "6500", "name": "Support Queue", "strategy": "rrmemory", "music_on_hold": "default", "ring_time": 15},
            {"queue_number": "6501", "name": "Sales Queue", "strategy": "leastrecent", "music_on_hold": "default", "ring_time": 15},
            {"queue_number": "6502", "name": "Billing Queue", "strategy": "linear", "music_on_hold": "default", "ring_time": 15}
        ])

    conn.commit()
    conn.close()


def _recording_value_aliases(value):
    """Return safe comparison forms for an extension/number-like value."""
    value = str(value or "").strip().lower()
    if not value:
        return set()
    aliases = {value}
    compact = re.sub(r"[^0-9]", "", value)
    if compact:
        aliases.add(compact)
        # Permit common international-prefix formatting differences without
        # making a broad fuzzy match for short extensions.
        if len(compact) >= 10:
            aliases.add(compact[-10:])
    return aliases


def _recording_meaningful_parts(filename):
    """Extract filename parts that identify a call, excluding date suffixes."""
    if not filename or os.path.basename(filename) != filename:
        return []
    stem = os.path.splitext(filename)[0]
    parts = [part.strip() for part in stem.split("-") if part.strip()]
    # Generated names end with YYYYMMDD-HHMMSS. Keep compatibility with
    # older/test filenames that do not have that suffix.
    if len(parts) >= 2 and re.fullmatch(r"\d{8}", parts[-2]) and re.fullmatch(r"\d{6}", parts[-1]):
        parts = parts[:-2]
    return parts


def _recording_file_aliases(filename):
    """Return endpoint/path identifiers encoded in a recording filename."""
    aliases = set()
    for part in _recording_meaningful_parts(filename):
        aliases.update(_recording_value_aliases(part))
        # Route IDs may be alphanumeric (for example main_route_id), while
        # their DID/caller components remain numeric.
        for numeric in re.findall(r"\d+", part):
            aliases.update(_recording_value_aliases(numeric))
    return aliases


def _recording_call_id(filename):
    """Return the exact linkedid embedded in a new-format recording name."""
    if not filename or os.path.basename(filename) != filename:
        return ""
    match = re.match(r"^rcm-(\d+)-", os.path.splitext(filename)[0], re.IGNORECASE)
    return match.group(1) if match else ""


def _recording_expected_times(uniqueid, duration=0, billsec=0, start_time="", end_time=""):
    """Build possible end times for a CDR, tolerating legacy CSV layouts."""
    times = []
    try:
        base = float(str(uniqueid or "").split("#", 1)[0])
        for offset in (duration, billsec, 0):
            times.append(base + max(0, int(offset or 0)))
    except (TypeError, ValueError):
        pass
    for value in (end_time, start_time):
        try:
            parsed = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            times.append(parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            pass
    return times


def find_recording_for_cdr(
    src,
    dst,
    uniqueid,
    duration=0,
    billsec=0,
    start_time="",
    end_time="",
    userfield="",
    extra_parties=(),
    _refresh_attempted=False,
):
    """Find the MixMonitor file belonging to a CDR row.

    Recording names are generated by several dialplan features:
    ``caller-destination``, ``queue-queue-caller``, ``ivr-ivr-caller``,
    ``ringgroup-group-caller``, ``paging-page-caller`` and ``in-route-did-caller``.
    The path/destination values in ``userfield`` let one CDR match the first
    recording trigger even when the final CDR destination is a queue/agent.
    """
    monitor_folder = MONITOR_RECORDING_DIR
    if not uniqueid or not os.path.isdir(monitor_folder):
        return ""

    uniqueid_base = str(uniqueid or "").split("#", 1)[0].strip()
    call_id_aliases = _recording_value_aliases(uniqueid_base)
    source_aliases = _recording_value_aliases(src)
    destination_aliases = _recording_value_aliases(dst)
    for party in extra_parties or ():
        destination_aliases.update(_recording_value_aliases(party))
    for numeric in re.findall(r"\d+", str(userfield or "")):
        destination_aliases.update(_recording_value_aliases(numeric))
    expected_times = _recording_expected_times(uniqueid, duration, billsec, start_time, end_time)
    if not call_id_aliases and not source_aliases:
        return ""

    best_match = ""
    min_diff = float("inf")
    try:
        try:
            folder_mtime = os.stat(monitor_folder).st_mtime_ns
        except OSError:
            folder_mtime = None
        if _RECORDING_INDEX["folder_mtime"] != folder_mtime:
            indexed_files = []
            for candidate in os.listdir(monitor_folder):
                if not candidate.lower().endswith(".wav"):
                    continue
                candidate_path = os.path.join(monitor_folder, candidate)
                try:
                    candidate_size = os.path.getsize(candidate_path)
                    candidate_mtime = os.path.getmtime(candidate_path)
                except OSError:
                    continue
                indexed_files.append((candidate, candidate_path, candidate_size, candidate_mtime))
            _RECORDING_INDEX["folder_mtime"] = folder_mtime
            _RECORDING_INDEX["files"] = indexed_files
        for filename, path, file_size, file_mtime in _RECORDING_INDEX["files"]:
            if not filename.lower().endswith(".wav"):
                continue
            try:
                if not os.path.isfile(path) or os.path.getsize(path) <= 44:
                    continue
                file_mtime = os.path.getmtime(path)
                embedded_call_id = _recording_call_id(filename)
                if embedded_call_id:
                    # New files are authoritative: an exact call-id match is
                    # accepted, while a different call-id is never guessed
                    # from caller/queue names or nearby timestamps.
                    if not (call_id_aliases & _recording_value_aliases(embedded_call_id)):
                        continue
                    diff = min(
                        (abs(file_mtime - moment) for moment in expected_times),
                        default=0,
                    )
                    if diff <= 300 and diff < min_diff:
                        min_diff = diff
                        best_match = filename
                    continue
                if not source_aliases:
                    continue
                file_aliases = _recording_file_aliases(filename)
                if not (source_aliases & file_aliases):
                    continue
                # Require a destination/path identifier whenever one is
                # available. This avoids attaching another call from the same
                # caller solely because it ended near the same time.
                if destination_aliases and not (destination_aliases & file_aliases):
                    # Older CDR rows may not carry UserField. For generated
                    # feature recordings, the feature prefix plus caller and
                    # close end time is still a safe legacy fallback. Direct
                    # recordings remain strict caller/destination matches.
                    prefix = _recording_meaningful_parts(filename)[0].lower() if _recording_meaningful_parts(filename) else ""
                    if prefix not in {"in", "ivr", "queue", "q", "ringgroup", "paging", "intercom"}:
                        continue
                diff = min(abs(file_mtime - moment) for moment in expected_times)
                # Legacy names have no exact call identifier. Keep their
                # fallback deliberately narrow so one old recording cannot be
                # attached to several calls just because they are nearby.
                if diff <= 30 and diff < min_diff:
                    min_diff = diff
                    best_match = filename
            except OSError:
                continue
    except OSError:
        return ""
    if not best_match and not _refresh_attempted:
        # Directory mtimes are not reliable on every filesystem used for the
        # monitor spool. Refresh once on a miss so a just-created recording is
        # never hidden behind a stale index.
        _RECORDING_INDEX["folder_mtime"] = None
        return find_recording_for_cdr(
            src, dst, uniqueid, duration, billsec, start_time, end_time,
            userfield, extra_parties, _refresh_attempted=True,
        )
    return best_match


def find_recording_for_queue_call(caller, agent, callid, wait_time, talk_time, queue=None):
    """Backward-compatible queue lookup using the unified CDR matcher."""
    return find_recording_for_cdr(
        src=caller,
        dst=queue or agent,
        uniqueid=callid,
        duration=max(0, int(wait_time or 0)) + max(0, int(talk_time or 0)),
        billsec=talk_time,
        extra_parties=(agent,) if agent else (),
    )


def get_queue_sessions(queue_num, filters=None):
    import rcm_queue_db
    return rcm_queue_db.get_queue_sessions(queue_num, filters)


def get_queue_pauses(queue_num, filters=None):
    import rcm_queue_db
    return rcm_queue_db.get_queue_pauses(queue_num, filters)


def get_mail_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mail_settings WHERE id = 1")
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def save_mail_settings(data):
    conn = get_db()
    c = conn.cursor()
    pw = data.get("password", "")
    if pw == "CLEAR_PASSWORD":
        c.execute("""
            INSERT INTO mail_settings (
                id, provider, smtp_server, smtp_port, encryption, sender_email, display_name, username, password,
                missed_calls_alert_enabled, missed_calls_threshold, cdr_report_enabled, cdr_report_email, cdr_report_schedule,
                cdr_report_time, cdr_report_weekday, cdr_report_month_day
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                smtp_server = excluded.smtp_server,
                smtp_port = excluded.smtp_port,
                encryption = excluded.encryption,
                sender_email = excluded.sender_email,
                display_name = excluded.display_name,
                username = excluded.username,
                password = '',
                missed_calls_alert_enabled = excluded.missed_calls_alert_enabled,
                missed_calls_threshold = excluded.missed_calls_threshold,
                cdr_report_enabled = excluded.cdr_report_enabled,
                cdr_report_email = excluded.cdr_report_email,
                cdr_report_schedule = excluded.cdr_report_schedule,
                cdr_report_time = excluded.cdr_report_time,
                cdr_report_weekday = excluded.cdr_report_weekday,
                cdr_report_month_day = excluded.cdr_report_month_day
        """, (
            data.get("provider", ""),
            data.get("smtp_server", ""),
            int(data.get("smtp_port", 25)) if str(data.get("smtp_port", "")).isdigit() else 25,
            data.get("encryption", "none"),
            data.get("sender_email", ""),
            data.get("display_name", ""),
            data.get("username", ""),
            int(data.get("missed_calls_alert_enabled", 0)),
            int(data.get("missed_calls_threshold", 5)) if str(data.get("missed_calls_threshold", "")).isdigit() else 5,
            int(data.get("cdr_report_enabled", 0)),
            data.get("cdr_report_email", ""),
            data.get("cdr_report_schedule", "weekly"),
            data.get("cdr_report_time", "09:00"),
            int(data.get("cdr_report_weekday", 0)) if str(data.get("cdr_report_weekday", "")).isdigit() else 0,
            int(data.get("cdr_report_month_day", 1)) if str(data.get("cdr_report_month_day", "")).isdigit() else 1
        ))
    else:
        c.execute("""
            INSERT INTO mail_settings (
                id, provider, smtp_server, smtp_port, encryption, sender_email, display_name, username, password,
                missed_calls_alert_enabled, missed_calls_threshold, cdr_report_enabled, cdr_report_email, cdr_report_schedule,
                cdr_report_time, cdr_report_weekday, cdr_report_month_day
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                smtp_server = excluded.smtp_server,
                smtp_port = excluded.smtp_port,
                encryption = excluded.encryption,
                sender_email = excluded.sender_email,
                display_name = excluded.display_name,
                username = excluded.username,
                password = CASE WHEN excluded.password != '' THEN excluded.password ELSE password END,
                missed_calls_alert_enabled = excluded.missed_calls_alert_enabled,
                missed_calls_threshold = excluded.missed_calls_threshold,
                cdr_report_enabled = excluded.cdr_report_enabled,
                cdr_report_email = excluded.cdr_report_email,
                cdr_report_schedule = excluded.cdr_report_schedule,
                cdr_report_time = excluded.cdr_report_time,
                cdr_report_weekday = excluded.cdr_report_weekday,
                cdr_report_month_day = excluded.cdr_report_month_day
        """, (
            data.get("provider", ""),
            data.get("smtp_server", ""),
            int(data.get("smtp_port", 25)) if str(data.get("smtp_port", "")).isdigit() else 25,
            data.get("encryption", "none"),
            data.get("sender_email", ""),
            data.get("display_name", ""),
            data.get("username", ""),
            pw,
            int(data.get("missed_calls_alert_enabled", 0)),
            int(data.get("missed_calls_threshold", 5)) if str(data.get("missed_calls_threshold", "")).isdigit() else 5,
            int(data.get("cdr_report_enabled", 0)),
            data.get("cdr_report_email", ""),
            data.get("cdr_report_schedule", "weekly"),
            data.get("cdr_report_time", "09:00"),
            int(data.get("cdr_report_weekday", 0)) if str(data.get("cdr_report_weekday", "")).isdigit() else 0,
            int(data.get("cdr_report_month_day", 1)) if str(data.get("cdr_report_month_day", "")).isdigit() else 1
        ))
    conn.commit()
    conn.close()

def log_email(receiver, sender, subject, status, error_msg, feature):
    import datetime
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO mail_logs (receiver_email, sender_email, subject, status, timestamp, error_message, feature)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (receiver, sender, subject, status, now_str, error_msg, feature))
    conn.commit()
    conn.close()

def get_mail_logs(limit=100):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mail_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def hash_otp(otp):
    import hashlib
    return hashlib.sha256(otp.encode('utf-8')).hexdigest()

def create_otp(username, email, otp, expires_in_minutes=5):
    import datetime
    conn = get_db()
    c = conn.cursor()
    
    # Mark old OTPs as invalid/verified so they can't be reused
    c.execute("UPDATE otp_records SET verified = 1 WHERE username = ?", (username,))
    
    now = datetime.datetime.now()
    expires_at = now + datetime.timedelta(minutes=expires_in_minutes)
    
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")
    
    hashed_otp = hash_otp(otp)
    c.execute("""
        INSERT INTO otp_records (username, email, otp, created_at, expires_at, attempts, verified)
        VALUES (?, ?, ?, ?, ?, 0, 0)
    """, (username, email, hashed_otp, now_str, expires_str))
    conn.commit()
    conn.close()

def verify_otp(username, otp):
    import datetime
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT * FROM otp_records 
        WHERE username = ? AND verified = 0 
        ORDER BY id DESC LIMIT 1
    """, (username,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return False, "No active OTP request found."
        
    otp_id = row["id"]
    db_otp = row["otp"]
    expires_at_str = row["expires_at"]
    attempts = row["attempts"]
    
    # Limit attempts
    if attempts >= 3:
        c.execute("UPDATE otp_records SET verified = 1 WHERE id = ?", (otp_id,))
        conn.commit()
        conn.close()
        return False, "Too many wrong attempts. Please request a new OTP."
        
    # Check expiry
    expires_at = datetime.datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
    if datetime.datetime.now() > expires_at:
        c.execute("UPDATE otp_records SET verified = 1 WHERE id = ?", (otp_id,))
        conn.commit()
        conn.close()
        return False, "OTP has expired. Please request a new one."
        
    hashed_input = hash_otp(otp)
    if db_otp != hashed_input:
        c.execute("UPDATE otp_records SET attempts = attempts + 1 WHERE id = ?", (otp_id,))
        conn.commit()
        conn.close()
        return False, f"Invalid OTP. {2 - attempts} attempts remaining."
        
    # Correct OTP
    c.execute("UPDATE otp_records SET verified = 1 WHERE id = ?", (otp_id,))
    conn.commit()
    conn.close()
    return True, ""

def update_user_password(username, new_password):
    conn = get_db()
    c = conn.cursor()
    if not (new_password.startswith('pbkdf2:') or new_password.startswith('scrypt:')):
        hashed = generate_password_hash(new_password)
    else:
        hashed = new_password
    c.execute("UPDATE users SET password = ?, session_version = COALESCE(session_version, 1) + 1 WHERE username = ?", (hashed, username))
    conn.commit()
    conn.close()

def get_user_by_username(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def add_to_mail_queue(receiver, subject, body_html, body_text, attachments, feature):
    import datetime
    import json
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO mail_queue (receiver_email, subject, body_html, body_text, attachments_json, feature, attempts, next_retry, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (receiver, subject, body_html, body_text, json.dumps(attachments or []), feature, now_str, now_str))
    conn.commit()
    conn.close()

def get_pending_mail_queue():
    import datetime
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        SELECT * FROM mail_queue 
        WHERE next_retry <= ? AND attempts < 3
    """, (now_str,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_mail_queue_attempt(queue_id, attempts, next_retry_minutes=5):
    import datetime
    conn = get_db()
    c = conn.cursor()
    now = datetime.datetime.now()
    next_retry = now + datetime.timedelta(minutes=next_retry_minutes)
    next_retry_str = next_retry.strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        UPDATE mail_queue 
        SET attempts = ?, next_retry = ? 
        WHERE id = ?
    """, (attempts, next_retry_str, queue_id))
    conn.commit()
    conn.close()

def delete_from_mail_queue(queue_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM mail_queue WHERE id = ?", (queue_id,))
    conn.commit()
    conn.close()

def sync_inbound_routes_from_json():
    routes = get_inbound_routes()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inbound_routes")
    for r in routes:
        cursor.execute("INSERT OR REPLACE INTO inbound_routes (id, name, priority, data) VALUES (?, ?, ?, ?)",
                       (r.get("id"), r.get("name"), r.get("priority", 0), json.dumps(r)))
    conn.commit()
    conn.close()

def sync_outbound_routes_from_json():
    routes = get_outbound_routes()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM outbound_routes")
    for r in routes:
        cursor.execute("INSERT OR REPLACE INTO outbound_routes (name, description, data) VALUES (?, ?, ?)",
                       (r.get("name"), r.get("description", ""), json.dumps(r)))
    conn.commit()
    conn.close()

def sync_queues_from_json():
    queues = get_queues()
    import rcm_queue_db
    conn = rcm_queue_db.get_db_connection()
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE queues ADD COLUMN data TEXT")
        conn.commit()
    except Exception:
        pass
        
    c.execute("DELETE FROM queues")
    for q in queues:
        q_num = q.get("queue_number", "").strip()
        name = q.get("name", "").strip()
        strategy = q.get("strategy", "rrmemory")
        max_members = int(q.get("max_queue_length", 0) or 0)
        timeout = int(q.get("ring_time", 0) or 0)
        retry = int(q.get("retry_time", 0) or 0)
        c.execute("""
            INSERT INTO queues (queue_number, queue_name, strategy, max_members, timeout, retry, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (q_num, name, strategy, max_members, timeout, retry, json.dumps(q)))
    conn.commit()
    conn.close()

def _normalize_asterisk_cdr_timestamp(value):
    """Convert a UTC timestamp from Asterisk CDR CSV to system local time.

    ``cdr.conf`` uses ``usegmtime=yes`` on this installation, so all three
    CDR lifecycle timestamps (start, answer and end) arrive in UTC.  Keep
    invalid/empty values unchanged because Asterisk uses sentinel values for
    unanswered calls.
    """
    value = str(value or "").strip()
    if not value or value == "0000-00-00 00:00:00":
        return value
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return parsed.astimezone(PBX_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return value


def _sync_cdr_records_locked():
    import csv
    import io
    filepath = CDR_CSV_PATH
    if not os.path.exists(filepath):
        return
        
    conn = get_db()
    cursor = conn.cursor()
    new_records = []
    seen_storage_ids = set()
    state_path = DB_PATH + ".cdr-sync.json"
    
    try:
        state = {}
        try:
            with open(state_path, "r", encoding="utf-8") as state_handle:
                state = json.load(state_handle)
        except (OSError, ValueError, TypeError):
            state = {}
        with open(filepath, 'r', encoding='utf-8') as f:
            f.seek(0)
            source_head = hashlib.sha1(f.read(512).encode("utf-8", errors="replace")).hexdigest()
            f.seek(0, 2)
            source_size = f.tell()
            source_offset = int(state.get("offset", 0) or 0)
            reset_source = (
                not state
                or source_offset > source_size
                or (state.get("head_hash") and state.get("head_hash") != source_head)
            )
            source_offset = 0 if reset_source else source_offset
            f.seek(source_offset)
            source_text = f.read()
            imported_offset = f.tell()
            if not source_text:
                try:
                    with open(state_path, "w", encoding="utf-8") as state_handle:
                        json.dump({"head_hash": source_head, "size": source_size, "offset": imported_offset}, state_handle)
                except OSError:
                    pass
                conn.close()
                return
            reader = csv.reader(io.StringIO(source_text))
            existing_fallback = {}
            if reset_source:
                for existing in cursor.execute(
                    "SELECT uniqueid, channel, dstchannel, start_time, end_time FROM cdr_records"
                ).fetchall():
                    existing_fallback.setdefault(str(existing["uniqueid"] or ""), []).append(existing)
            else:
                seen_storage_ids.update(
                    str(existing["uniqueid"] or "")
                    for existing in cursor.execute("SELECT uniqueid FROM cdr_records").fetchall()
                    if existing["uniqueid"]
                )
            for row in reader:
                if len(row) >= 15:
                    uniqueid = str(row[16] if len(row) > 16 else "").strip()
                    if not uniqueid:
                        continue
                    
                    src = row[1]
                    dst = row[2]
                    dcontext = row[3]
                    clid = row[4].replace('"', '')
                    channel = row[5]
                    dstchannel = row[6]
                    lastapp = row[7]
                    lastdata = row[8]
                    start_str = _normalize_asterisk_cdr_timestamp(row[9])
                    answer_str = _normalize_asterisk_cdr_timestamp(row[10])
                    end_str = _normalize_asterisk_cdr_timestamp(row[11])
                    duration = int(row[12]) if row[12].isdigit() else 0
                    billsec = int(row[13]) if row[13].isdigit() else 0
                    disposition = row[14]
                    # The active legacy layout has UniqueID at 16 and
                    # UserField at 17. With newcdrcolumns=yes Asterisk adds
                    # peeraccount, linkedid and sequence after UserField;
                    # accept that layout too. When linkedid is unavailable,
                    # UniqueID is the safest grouping key for this installation.
                    linkedid = uniqueid
                    userfield = row[17] if len(row) > 17 else ""
                    if len(row) >= 20 and re.fullmatch(r"\d+\.\d+", str(row[19] or "").strip()):
                        linkedid = str(row[19]).strip() or uniqueid

                    # Asterisk commonly emits multiple channels with the same
                    # UniqueID. The database key must remain unique for
                    # compatibility, so only duplicate storage keys get a
                    # deterministic leg suffix; all rows still share linkedid.
                    storage_uid = uniqueid
                    if reset_source:
                        candidates = existing_fallback.get(uniqueid) or []
                        exact = next(
                            (
                                item for item in candidates
                                if str(item["channel"] or "") == str(channel or "")
                                and str(item["dstchannel"] or "") == str(dstchannel or "")
                                and str(item["start_time"] or "") == str(start_str or "")
                                and str(item["end_time"] or "") == str(end_str or "")
                            ),
                            None,
                        )
                        if exact is not None:
                            storage_uid = str(exact["uniqueid"])
                            candidates.remove(exact)
                        elif candidates and uniqueid not in seen_storage_ids:
                            storage_uid = uniqueid
                            candidates.pop(0)
                    if storage_uid in seen_storage_ids:
                        digest = hashlib.sha1(
                            "|".join(str(value or "") for value in row[5:12]).encode("utf-8")
                        ).hexdigest()[:12]
                        storage_uid = f"{uniqueid}#leg-{digest}"
                        serial = 2
                        while storage_uid in seen_storage_ids:
                            storage_uid = f"{uniqueid}#leg-{digest}-{serial}"
                            serial += 1
                    seen_storage_ids.add(storage_uid)
                    
                    recording = find_recording_for_cdr(
                        src=src,
                        dst=dst,
                        uniqueid=uniqueid,
                        duration=duration,
                        billsec=billsec,
                        start_time=start_str,
                        end_time=end_str,
                        userfield=userfield,
                        extra_parties=(
                            re.findall(r"(?:PJSIP|SIP)/([0-9]+)", channel or "")
                            + re.findall(r"(?:PJSIP|SIP)/([0-9]+)", dstchannel or "")
                        ),
                    )

                    new_records.append((
                        storage_uid, linkedid, src, dst, clid, channel, dstchannel, dcontext, lastapp, lastdata,
                        start_str, answer_str, end_str, duration, billsec, disposition, recording, userfield
                    ))
    except Exception as e:
        print(f"Error reading CSV in sync: {e}")
        
    if new_records:
        cursor.executemany('''
            INSERT INTO cdr_records
            (uniqueid, linkedid, src, dst, clid, channel, dstchannel, dcontext, lastapp, lastdata, start_time, answer_time, end_time, duration, billsec, status, recording, userfield)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniqueid) DO UPDATE SET
                linkedid = excluded.linkedid,
                src = excluded.src,
                dst = excluded.dst,
                clid = excluded.clid,
                channel = excluded.channel,
                dstchannel = excluded.dstchannel,
                dcontext = excluded.dcontext,
                lastapp = excluded.lastapp,
                lastdata = excluded.lastdata,
                start_time = excluded.start_time,
                answer_time = excluded.answer_time,
                end_time = excluded.end_time,
                duration = excluded.duration,
                billsec = excluded.billsec,
                status = excluded.status,
                recording = COALESCE(excluded.recording, cdr_records.recording),
                userfield = excluded.userfield
        ''', new_records)
        conn.commit()
    try:
        with open(state_path, "w", encoding="utf-8") as state_handle:
            json.dump({"head_hash": source_head, "size": source_size, "offset": imported_offset}, state_handle)
    except (NameError, OSError):
        pass
    conn.close()


def sync_cdr_records():
    """Import only new CDR CSV bytes while keeping repeated calls safe."""
    with _CDR_SYNC_LOCK:
        return _sync_cdr_records_locked()

# --- User Management & Privilege Helpers ---

def get_users_list(search="", status="", privilege_id="", limit=200, offset=0):
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT u.id, u.username, u.email, u.role, u.legacy_role, u.status, u.privilege_id, COALESCE(NULLIF(u.system_key, ''), p.system_key) AS system_key, u.session_version, u.created_at, u.updated_at,
               p.name AS privilege_name, p.is_protected AS privilege_protected, p.legacy_role AS priv_legacy, p.system_key AS priv_system_key
        FROM users u
        LEFT JOIN privileges p ON u.privilege_id = p.id
        WHERE u.user_type = 'management'
    """
    params = []
    if search:
        query += " AND (u.username LIKE ? OR u.email LIKE ? OR p.name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if status:
        query += " AND u.status = ?"
        params.append(status)
    if privilege_id:
        query += " AND u.privilege_id = ?"
        params.append(privilege_id)
    query += " ORDER BY u.username ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    
    # Get total count
    count_query = "SELECT COUNT(*) FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.user_type = 'management'"
    count_params = []
    if search:
        count_query += " AND (u.username LIKE ? OR u.email LIKE ? OR p.name LIKE ?)"
        count_params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if status:
        count_query += " AND u.status = ?"
        count_params.append(status)
    if privilege_id:
        count_query += " AND u.privilege_id = ?"
        count_params.append(privilege_id)
    c.execute(count_query, count_params)
    total = c.fetchone()[0]
    conn.close()
    return rows, total

def get_users_management_stats(search="", status="", privilege_id=""):
    """Return summary counts for the complete filtered management-user result set."""
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN u.status = 'enabled' THEN 1 ELSE 0 END) AS enabled,
            SUM(CASE WHEN u.status = 'disabled' THEN 1 ELSE 0 END) AS disabled,
            SUM(CASE WHEN u.legacy_role = 'admin' THEN 1 ELSE 0 END) AS admins
        FROM users u
        LEFT JOIN privileges p ON u.privilege_id = p.id
        WHERE u.user_type = 'management'
    """
    params = []
    if search:
        query += " AND (u.username LIKE ? OR u.email LIKE ? OR p.name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if status:
        query += " AND u.status = ?"
        params.append(status)
    if privilege_id:
        query += " AND u.privilege_id = ?"
        params.append(privilege_id)
    c.execute(query, params)
    row = dict(c.fetchone())
    conn.close()
    return {key: int(value or 0) for key, value in row.items()}

def get_user_by_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT u.*, p.name AS privilege_name, p.is_protected AS privilege_protected, p.legacy_role AS priv_legacy
        FROM users u
        LEFT JOIN privileges p ON u.privilege_id = p.id
        WHERE u.id = ?
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username, password, email="", privilege_id=None, status="enabled", caller_system_key=None):
    conn = get_db()
    c = conn.cursor()
    try:
        username = str(username or "").strip()
        email = str(email or "").strip()
        status = str(status or "").strip().lower()
        if status not in VALID_USER_STATUSES:
            return False, None, "Invalid account status."
        if privilege_id is None:
            return False, None, "Privilege is required."

        legacy_role = 'agent'
        c.execute("SELECT legacy_role, is_protected, system_key FROM privileges WHERE id = ?", (privilege_id,))
        prow = c.fetchone()
        if not prow:
            return False, None, "Privilege not found."
        prow = dict(prow)
        if (prow.get("is_protected") == 1 or prow.get("system_key") == 'super_admin') and caller_system_key is not None and caller_system_key != 'super_admin':
            return False, None, "Only Super Admin accounts can assign protected roles."
        if prow.get("legacy_role") in VALID_LEGACY_ROLES:
            legacy_role = prow["legacy_role"]

        if email:
            c.execute("SELECT id FROM users WHERE user_type = 'management' AND lower(email) = lower(?)", (email,))
            if c.fetchone():
                return False, None, "Email address already exists."
        hashed = generate_password_hash(password) if not (password.startswith('pbkdf2:') or password.startswith('scrypt:')) else password
        c.execute("""
            INSERT INTO users (username, password, role, email, privilege_id, status, session_version, legacy_role, user_type, extension_ext)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'management', NULL)
        """, (username, hashed, legacy_role, email, privilege_id, status, legacy_role))
        user_id = c.lastrowid
        conn.commit()
        return True, user_id, ""
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "email" in str(exc).lower() or "idx_management_users_email_unique" in str(exc).lower():
            return False, None, "Email address already exists."
        return False, None, "Username already exists."
    except Exception as e:
        conn.rollback()
        return False, None, str(e)
    finally:
        conn.close()

def update_user(user_id, username=None, password=None, email=None, privilege_id=None, status=None, caller_system_key=None):
    conn = get_db()
    c = conn.cursor()
    try:
        if status is not None:
            status = str(status).strip().lower()
            if status not in VALID_USER_STATUSES:
                return False, "Invalid account status."
        if privilege_id is not None and caller_system_key is not None and caller_system_key != 'super_admin':
            c.execute("SELECT is_protected, system_key FROM privileges WHERE id = ?", (privilege_id,))
            requested_privilege = c.fetchone()
            if requested_privilege:
                requested_privilege = dict(requested_privilege)
                if requested_privilege.get("is_protected") == 1 or requested_privilege.get("system_key") == 'super_admin':
                    return False, "Only Super Admin accounts can assign protected roles."
        c.execute("SELECT u.*, p.is_protected AS priv_protected, p.system_key AS priv_system_key FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.id = ?", (user_id,))
        old = c.fetchone()
        if not old:
            return False, "User not found."
        old = dict(old)
        if old.get("user_type") == "extension_user":
            return False, "Extension Web Users are managed from their Extension page."
            
        if caller_system_key is not None and caller_system_key != 'super_admin':
            if old.get("priv_protected") == 1 or old.get("priv_system_key") == 'super_admin' or old.get("legacy_role") == "admin":
                return False, "Only Super Admin accounts can modify users with protected roles."

        if email is not None:
            email = str(email).strip()
            if email:
                c.execute("SELECT id FROM users WHERE user_type = 'management' AND lower(email) = lower(?) AND id != ?", (email, user_id))
                if c.fetchone():
                    return False, "Email address already exists."

        if privilege_id is not None:
            c.execute("SELECT legacy_role FROM privileges WHERE id = ?", (privilege_id,))
            if not c.fetchone():
                return False, "Privilege not found."
            
        fields = []
        params = []
        if username is not None and username != old["username"]:
            fields.append("username = ?")
            params.append(username)
        if password is not None and password.strip() != "":
            hashed = generate_password_hash(password) if not (password.startswith('pbkdf2:') or password.startswith('scrypt:')) else password
            fields.append("password = ?")
            params.append(hashed)
        if email is not None:
            fields.append("email = ?")
            params.append(email)
        if privilege_id is not None and privilege_id != old["privilege_id"]:
            if caller_system_key is not None and caller_system_key != 'super_admin':
                c.execute("SELECT is_protected, system_key FROM privileges WHERE id = ?", (privilege_id,))
                new_p = c.fetchone()
                if new_p:
                    new_p = dict(new_p)
                    if new_p.get("is_protected") == 1 or new_p.get("system_key") == 'super_admin':
                        return False, "Only Super Admin accounts can assign protected roles."
            if old.get("legacy_role") == "admin" or old.get("priv_system_key") == "super_admin":
                c.execute("""
                    SELECT COUNT(*)
                    FROM users u
                    LEFT JOIN privileges p ON u.privilege_id = p.id
                    WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin')
                      AND u.status = 'enabled'
                      AND u.id != ?
                """, (user_id,))
                if c.fetchone()[0] == 0:
                    return False, "Cannot demote the last active Super Admin account."
            fields.append("privilege_id = ?")
            params.append(privilege_id)
            c.execute("SELECT legacy_role FROM privileges WHERE id = ?", (privilege_id,))
            prow = c.fetchone()
            if prow:
                prow = dict(prow)
                if prow.get("legacy_role"):
                    fields.append("role = ?")
                    params.append(prow["legacy_role"])
                    fields.append("legacy_role = ?")
                    params.append(prow["legacy_role"])
        if status is not None and status != old["status"]:
            if status == "disabled" and (old.get("legacy_role") == "admin" or old.get("priv_system_key") == "super_admin"):
                c.execute("""
                    SELECT COUNT(*)
                    FROM users u
                    LEFT JOIN privileges p ON u.privilege_id = p.id
                    WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin')
                      AND u.status = 'enabled'
                      AND u.id != ?
                """, (user_id,))
                if c.fetchone()[0] == 0:
                    return False, "Cannot disable the last active Super Admin account."
            fields.append("status = ?")
            params.append(status)
            
        if fields:
            fields.append("session_version = COALESCE(session_version, 1) + 1")
            query = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
            params.append(user_id)
            c.execute(query, params)
            conn.commit()
        return True, ""
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "email" in str(exc).lower() or "idx_management_users_email_unique" in str(exc).lower():
            return False, "Email address already exists."
        return False, "Username already exists."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def delete_user(user_id, caller_system_key=None):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT u.*, p.is_protected, p.system_key FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            return False, "User not found."
        row = dict(row)
        if row.get("user_type") == "extension_user":
            return False, "Extension Web Users are deleted with their Extension."
        if caller_system_key is not None and caller_system_key != 'super_admin':
            if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
                return False, "Only Super Admin accounts can delete users with protected roles."
        if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
            c.execute("""
                SELECT COUNT(*) FROM users u 
                LEFT JOIN privileges p ON u.privilege_id = p.id 
                WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin') AND u.id != ? AND u.status = 'enabled'
            """, (user_id,))
            if c.fetchone()[0] == 0:
                return False, "Cannot delete the last active Super Admin account."
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def bump_user_session_version(user_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET session_version = COALESCE(session_version, 1) + 1 WHERE id = ?", (user_id,))
        if c.rowcount == 0:
            return False, "User not found."
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def update_user_profile(username, email=None, current_password=None, new_password=None):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        if not row:
            return False, "User not found."
        row = dict(row)
        
        fields = []
        params = []
        if email is not None and email != row.get("email"):
            fields.append("email = ?")
            params.append(email)
            
        if new_password and new_password.strip():
            if not current_password:
                return False, "Current password is required to change password."
            # Verify current password
            stored = row["password"]
            if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
                if not check_password_hash(stored, current_password):
                    return False, "Incorrect current password."
            else:
                if stored != current_password:
                    return False, "Incorrect current password."
                    
            hashed = generate_password_hash(new_password)
            fields.append("password = ?")
            params.append(hashed)
            fields.append("session_version = COALESCE(session_version, 1) + 1")
            
        if fields:
            query = f"UPDATE users SET {', '.join(fields)} WHERE username = ?"
            params.append(username)
            c.execute(query, params)
            conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def bulk_toggle_users(user_ids, status, caller_system_key=None, current_user_id=None):
    if status not in ("enabled", "disabled"):
        return False, 0, "Invalid status specified."
    conn = get_db()
    c = conn.cursor()
    count = 0
    try:
        for uid in user_ids:
            try:
                uid = int(uid)
            except (ValueError, TypeError):
                continue
            if current_user_id is not None and uid == int(current_user_id) and status == "disabled":
                continue
            c.execute("SELECT u.*, p.is_protected, p.system_key FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.id = ?", (uid,))
            row = c.fetchone()
            if not row:
                continue
            row = dict(row)
            if row.get("user_type") == "extension_user":
                continue
            if caller_system_key is not None and caller_system_key != 'super_admin':
                if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
                    continue
            if status == "disabled" and (row.get("legacy_role") == "admin" or row.get("system_key") == "super_admin"):
                c.execute("""
                    SELECT COUNT(*)
                    FROM users u
                    LEFT JOIN privileges p ON u.privilege_id = p.id
                    WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin')
                      AND u.status = 'enabled'
                      AND u.id != ?
                """, (uid,))
                if c.fetchone()[0] == 0:
                    continue
            c.execute("UPDATE users SET status = ?, session_version = COALESCE(session_version, 1) + 1 WHERE id = ?", (status, uid))
            if c.rowcount > 0:
                count += 1
        conn.commit()
        return True, count, ""
    except Exception as e:
        conn.rollback()
        return False, count, str(e)
    finally:
        conn.close()

def bulk_delete_users(user_ids, caller_system_key=None, current_user_id=None):
    conn = get_db()
    c = conn.cursor()
    count = 0
    try:
        for uid in user_ids:
            try:
                uid = int(uid)
            except (ValueError, TypeError):
                continue
            if current_user_id is not None and uid == int(current_user_id):
                continue
            c.execute("SELECT u.*, p.is_protected, p.system_key FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.id = ?", (uid,))
            row = c.fetchone()
            if not row:
                continue
            row = dict(row)
            if row.get("user_type") == "extension_user":
                continue
            if caller_system_key is not None and caller_system_key != 'super_admin':
                if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
                    continue
            if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
                c.execute("""
                    SELECT COUNT(*) FROM users u 
                    LEFT JOIN privileges p ON u.privilege_id = p.id 
                    WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin') AND u.id != ? AND u.status = 'enabled'
                """, (uid,))
                if c.fetchone()[0] == 0:
                    continue
            c.execute("DELETE FROM users WHERE id = ?", (uid,))
            if c.rowcount > 0:
                count += 1
        conn.commit()
        return True, count, ""
    except Exception as e:
        conn.rollback()
        return False, count, str(e)
    finally:
        conn.close()

def bulk_assign_user_privilege(user_ids, privilege_id, caller_system_key=None, current_user_id=None):
    conn = get_db()
    c = conn.cursor()
    count = 0
    try:
        try:
            privilege_id = int(privilege_id)
        except (ValueError, TypeError):
            return False, 0, "Invalid target privilege."
            
        c.execute("SELECT * FROM privileges WHERE id = ?", (privilege_id,))
        prow = c.fetchone()
        if not prow:
            return False, 0, "Target privilege role not found."
        prow = dict(prow)
        
        if (prow.get("is_protected") == 1 or prow.get("system_key") == 'super_admin') and caller_system_key is not None and caller_system_key != 'super_admin':
            return False, 0, "Only Super Admin accounts can assign protected roles."
            
        new_legacy_role = prow.get("legacy_role", "agent")
        
        for uid in user_ids:
            try:
                uid = int(uid)
            except (ValueError, TypeError):
                continue
            c.execute("SELECT u.*, p.is_protected, p.system_key FROM users u LEFT JOIN privileges p ON u.privilege_id = p.id WHERE u.id = ?", (uid,))
            row = c.fetchone()
            if not row:
                continue
            row = dict(row)
            if row.get("user_type") == "extension_user":
                continue
            if caller_system_key is not None and caller_system_key != 'super_admin':
                if row.get("is_protected") == 1 or row.get("system_key") == 'super_admin' or row.get("legacy_role") == "admin":
                    continue
            if row.get("legacy_role") == "admin" or row.get("system_key") == "super_admin":
                if new_legacy_role != "admin":
                    c.execute("""
                        SELECT COUNT(*)
                        FROM users u
                        LEFT JOIN privileges p ON u.privilege_id = p.id
                        WHERE (p.system_key = 'super_admin' OR u.legacy_role = 'admin')
                          AND u.status = 'enabled'
                          AND u.id != ?
                    """, (uid,))
                    if c.fetchone()[0] == 0:
                        continue
            c.execute("UPDATE users SET privilege_id = ?, role = ?, legacy_role = ?, session_version = COALESCE(session_version, 1) + 1 WHERE id = ?", (privilege_id, new_legacy_role, new_legacy_role, uid))
            if c.rowcount > 0:
                count += 1
        conn.commit()
        return True, count, ""
    except Exception as e:
        conn.rollback()
        return False, count, str(e)
    finally:
        conn.close()

def get_privileges_list(search=""):
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT p.*, (SELECT COUNT(*) FROM users u WHERE u.privilege_id = p.id) AS user_count
        FROM privileges p
        WHERE 1=1
    """
    params = []
    if search:
        query += " AND (p.name LIKE ? OR p.description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY p.is_protected DESC, p.name ASC"
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_privilege_by_id(privilege_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM privileges WHERE id = ?", (privilege_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_privilege_permissions(privilege_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT module, action FROM privilege_permissions WHERE privilege_id = ?", (privilege_id,))
    perms = {(row["module"], row["action"]) for row in c.fetchall()}
    conn.close()
    return perms


def _reporting_scope_template():
    return {
        scope_type: {
            "all_data": False,
            "all_extensions": False,
            "all_queues": False,
            "all_ring_groups": False,
            "items": {group: [] for group in REPORTING_SCOPE_GROUPS},
        }
        for scope_type in REPORTING_SCOPE_TYPES
    }


def _scope_flag(value):
    return bool(value in (True, 1, "1", "true", "True", "on", "yes"))


def _reporting_scope_item(group, value):
    return f"{group[:-1] if group.endswith('s') else group}:{str(value)}"


def _parse_reporting_scope_item(scope_type, raw_value):
    raw_value = str(raw_value)
    if ":" in raw_value:
        group, value = raw_value.split(":", 1)
        group = {"extension": "extensions", "queue": "queues", "ring_group": "ring_groups"}.get(group, group)
        if group in REPORTING_SCOPE_GROUPS and value:
            return group, value
    # Legacy scopes stored queue IDs for queue scopes and extension IDs for
    # CDR/recording scopes without a group prefix.
    group = "queues" if scope_type in ("queue_live", "queue_stats") else "extensions"
    return group, raw_value


def normalize_reporting_scopes(scopes_dict):
    """Normalize new grouped scopes and the legacy flat scope payload."""
    normalized = _reporting_scope_template()
    if not isinstance(scopes_dict, dict):
        return normalized

    reporting = scopes_dict.get("reporting")
    if isinstance(reporting, dict):
        for scope_type in REPORTING_SCOPE_TYPES:
            source = reporting.get(scope_type) or {}
            if not isinstance(source, dict):
                continue
            target = normalized[scope_type]
            for flag in ("all_data", "all_extensions", "all_queues", "all_ring_groups"):
                target[flag] = _scope_flag(source.get(flag))
            raw_items = source.get("items") or {}
            if isinstance(raw_items, dict):
                for group in REPORTING_SCOPE_GROUPS:
                    values = raw_items.get(group) or []
                    if isinstance(values, (list, tuple, set)):
                        target["items"][group] = sorted({str(v) for v in values if str(v).strip()})
        for target in normalized.values():
            if target["all_data"]:
                target["all_extensions"] = target["all_queues"] = target["all_ring_groups"] = False
                target["items"] = {group: [] for group in REPORTING_SCOPE_GROUPS}
            elif target["all_extensions"]:
                target["all_queues"] = target["all_ring_groups"] = False
                target["items"]["queues"] = []
                target["items"]["ring_groups"] = []
            if target["all_queues"]:
                target["items"]["queues"] = []
            if target["all_ring_groups"]:
                target["items"]["ring_groups"] = []
        return normalized

    settings = scopes_dict.get("settings") or {}
    items = scopes_dict.get("items") or {}
    for scope_type in REPORTING_SCOPE_TYPES:
        mode = settings.get(scope_type, "none")
        target = normalized[scope_type]
        if mode == "all":
            if scope_type in ("queue_live", "queue_stats"):
                target["all_queues"] = True
            else:
                target["all_data"] = True
        elif mode == "selected":
            for value in items.get(scope_type, []) or []:
                group, item = _parse_reporting_scope_item(scope_type, value)
                target["items"][group].append(item)
            for group in REPORTING_SCOPE_GROUPS:
                target["items"][group] = sorted(set(target["items"][group]))
    return normalized


def _reporting_scope_mode(scope):
    if scope.get("all_data"):
        return "all"
    has_selection = any(scope.get(flag) for flag in ("all_extensions", "all_queues", "all_ring_groups"))
    has_selection = has_selection or any(scope.get("items", {}).get(group) for group in REPORTING_SCOPE_GROUPS)
    return "selected" if has_selection else "none"


def get_privilege_scopes(privilege_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT scope_type, scope_mode,
               COALESCE(all_data, 0) AS all_data,
               COALESCE(all_extensions, 0) AS all_extensions,
               COALESCE(all_queues, 0) AS all_queues,
               COALESCE(all_ring_groups, 0) AS all_ring_groups
        FROM privilege_scope_settings WHERE privilege_id = ?
    """, (privilege_id,))
    settings = {row["scope_type"]: row["scope_mode"] for row in c.fetchall()}
    c.execute("""
        SELECT scope_type, scope_mode,
               COALESCE(all_data, 0) AS all_data,
               COALESCE(all_extensions, 0) AS all_extensions,
               COALESCE(all_queues, 0) AS all_queues,
               COALESCE(all_ring_groups, 0) AS all_ring_groups
        FROM privilege_scope_settings WHERE privilege_id = ?
    """, (privilege_id,))
    reporting = _reporting_scope_template()
    for row in c.fetchall():
        if row["scope_type"] not in reporting:
            continue
        target = reporting[row["scope_type"]]
        for flag in ("all_data", "all_extensions", "all_queues", "all_ring_groups"):
            target[flag] = bool(row[flag])

    c.execute("SELECT scope_type, scope_id FROM privilege_scope_items WHERE privilege_id = ?", (privilege_id,))
    items = {}
    rows = c.fetchall()
    for row in rows:
        st = row["scope_type"]
        if st in reporting:
            group, item = _parse_reporting_scope_item(st, row["scope_id"])
            # Keep the legacy response shape, but expose one canonical ID
            # even when a database still contains a pre-migration raw item
            # beside its namespaced Reporting Scope item.
            items.setdefault(st, []).append(str(item))
            reporting[st]["items"][group].append(item)
        else:
            items.setdefault(st, []).append(row["scope_id"])
    for scope_type, values in list(items.items()):
        items[scope_type] = sorted(set(str(value) for value in values))
    for scope in reporting.values():
        for group in REPORTING_SCOPE_GROUPS:
            scope["items"][group] = sorted(set(scope["items"][group]))
    conn.close()

    return {"settings": settings, "items": items, "reporting": reporting}

def save_privilege_atomic(privilege_id, name, description, legacy_role, permissions_list, scopes_dict, caller_system_key=None):
    conn = get_db()
    c = conn.cursor()
    try:
        if legacy_role not in VALID_LEGACY_ROLES:
            return False, None, "Invalid compatible legacy role."
        if not isinstance(permissions_list, (list, tuple, set)):
            return False, None, "Permissions must be a list."
        if not isinstance(scopes_dict, dict):
            return False, None, "Scopes must be an object."
        if privilege_id is not None:
            c.execute("SELECT is_protected, system_key FROM privileges WHERE id = ?", (privilege_id,))
            protected_target = c.fetchone()
            if protected_target:
                protected_target = dict(protected_target)
                if protected_target.get("is_protected") == 1 and caller_system_key is not None and caller_system_key != 'super_admin':
                    return False, None, "Only Super Admin accounts can modify protected roles."
                if protected_target.get("system_key") == 'super_admin':
                    return False, None, "The built-in Super Admin privilege is read-only."
        normalized_permissions = []
        for permission in permissions_list:
            if not isinstance(permission, (list, tuple)) or len(permission) != 2:
                return False, None, "Invalid permission entry."
            normalized_permissions.append((str(permission[0]), str(permission[1])))
        c.execute("""
            SELECT pp.module, pp.action
            FROM privilege_permissions pp
            JOIN privileges p ON p.id = pp.privilege_id
            WHERE p.system_key = 'super_admin'
        """)
        allowed_permissions = {(row["module"], row["action"]) for row in c.fetchall()}
        if allowed_permissions and any(permission not in allowed_permissions for permission in normalized_permissions):
            return False, None, "One or more permissions are invalid."

        if not isinstance(scopes_dict.get("reporting", scopes_dict), dict):
            return False, None, "Reporting scopes must be an object."
        reporting_scopes = normalize_reporting_scopes(scopes_dict)
        is_protected = 0
        if privilege_id is not None:
            c.execute("SELECT name, is_protected, system_key FROM privileges WHERE id = ?", (privilege_id,))
            old = c.fetchone()
            if old:
                old = dict(old)
                if old.get("is_protected") == 1:
                    is_protected = 1
                    if caller_system_key is not None and caller_system_key != 'super_admin':
                        return False, None, "Only Super Admin accounts can modify protected roles."
                    if old.get("system_key") == 'super_admin':
                        return False, None, "The built-in Super Admin privilege is read-only."
        
        if privilege_id is None:
            c.execute("""
                INSERT INTO privileges (name, description, is_protected, legacy_role, created_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (name, description, is_protected, legacy_role))
            privilege_id = c.lastrowid
        else:
            c.execute("""
                UPDATE privileges
                SET name = ?, description = ?, legacy_role = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, description, legacy_role, privilege_id))
            c.execute("DELETE FROM privilege_permissions WHERE privilege_id = ?", (privilege_id,))
            c.execute("DELETE FROM privilege_scope_settings WHERE privilege_id = ?", (privilege_id,))
            c.execute("DELETE FROM privilege_scope_items WHERE privilege_id = ?", (privilege_id,))
            
        # Permissions are intentionally independent.  A user with an action
        # permission can access the module list (the authorization decorator
        # handles that), but that must not mutate the privilege by adding the
        # view action or any other CRUD action.
        final_perms = set(normalized_permissions)

        for mod, act in final_perms:
            c.execute("""
                INSERT OR IGNORE INTO privilege_permissions (privilege_id, module, action)
                VALUES (?, ?, ?)
            """, (privilege_id, mod, act))
            
        for stype, scope in reporting_scopes.items():
            smode = _reporting_scope_mode(scope)
            c.execute("""
                INSERT INTO privilege_scope_settings
                    (privilege_id, scope_type, scope_mode, all_data, all_extensions, all_queues, all_ring_groups, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                privilege_id, stype, smode,
                int(scope.get("all_data")), int(scope.get("all_extensions")),
                int(scope.get("all_queues")), int(scope.get("all_ring_groups")),
            ))
            for group, group_items in scope.get("items", {}).items():
                if group not in REPORTING_SCOPE_GROUPS:
                    continue
                for sid in group_items:
                    c.execute("""
                        INSERT OR IGNORE INTO privilege_scope_items (privilege_id, scope_type, scope_id)
                        VALUES (?, ?, ?)
                    """, (privilege_id, stype, _reporting_scope_item(group, sid)))
                    
        c.execute("UPDATE users SET session_version = COALESCE(session_version, 1) + 1 WHERE privilege_id = ?", (privilege_id,))
        conn.commit()
        return True, privilege_id, ""
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, None, "Privilege name already exists."
    except Exception as e:
        conn.rollback()
        return False, None, str(e)
    finally:
        conn.close()

def delete_privilege(privilege_id, fallback_privilege_id=None):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT is_protected, system_key, (SELECT COUNT(*) FROM users WHERE privilege_id = privileges.id) as ucount FROM privileges WHERE id = ?", (privilege_id,))
        row = c.fetchone()
        if not row:
            return False, "Privilege not found."
        row = dict(row)
        if row.get("is_protected") == 1 or row.get("system_key") in ('super_admin', 'supervisor', 'agent'):
            return False, "Cannot delete built-in system privileges."
        if row.get("ucount", 0) > 0:
            return False, f"Cannot delete privilege assigned to {row['ucount']} user(s). Reassign those users first."
            
        c.execute("DELETE FROM privileges WHERE id = ?", (privilege_id,))
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def duplicate_privilege(privilege_id, new_name, caller_system_key=None):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM privileges WHERE id = ?", (privilege_id,))
        old = c.fetchone()
        if not old:
            return False, None, "Source privilege not found."
        old = dict(old)
        if (old.get("is_protected") == 1 or old.get("system_key") == 'super_admin') and caller_system_key is not None and caller_system_key != 'super_admin':
            return False, None, "Only Super Admin accounts can duplicate protected roles."
            
        c.execute("""
            INSERT INTO privileges (name, description, is_protected, legacy_role, created_at, updated_at)
            VALUES (?, ?, 0, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (new_name, f"Copy of {old['name']}", old["legacy_role"]))
        new_id = c.lastrowid
        
        c.execute("""
            INSERT INTO privilege_permissions (privilege_id, module, action)
            SELECT ?, module, action FROM privilege_permissions WHERE privilege_id = ?
        """, (new_id, privilege_id))
        
        c.execute("""
            INSERT INTO privilege_scope_settings
                (privilege_id, scope_type, scope_mode, all_data, all_extensions, all_queues, all_ring_groups, created_at, updated_at)
            SELECT ?, scope_type, scope_mode,
                   COALESCE(all_data, 0), COALESCE(all_extensions, 0),
                   COALESCE(all_queues, 0), COALESCE(all_ring_groups, 0),
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM privilege_scope_settings WHERE privilege_id = ?
        """, (new_id, privilege_id))
        
        c.execute("""
            INSERT INTO privilege_scope_items (privilege_id, scope_type, scope_id, created_at)
            SELECT ?, scope_type, scope_id, CURRENT_TIMESTAMP FROM privilege_scope_items WHERE privilege_id = ?
        """, (new_id, privilege_id))
        
        conn.commit()
        return True, new_id, ""
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, None, "Privilege name already exists."
    except Exception as e:
        conn.rollback()
        return False, None, str(e)
    finally:
        conn.close()

def get_user_permissions_context(user_id_or_username):
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT u.id, u.username, u.status, u.session_version, u.privilege_id, u.legacy_role as user_legacy,
               u.user_type, u.extension_ext,
               p.name as privilege_name, p.is_protected, p.system_key, p.legacy_role as priv_legacy
        FROM users u
        LEFT JOIN privileges p ON u.privilege_id = p.id
        WHERE u.id = ?
    """
    if isinstance(user_id_or_username, int):
        c.execute(query, (user_id_or_username,))
    else:
        c.execute(query.replace("WHERE u.id = ?", "WHERE u.username = ?"), (str(user_id_or_username),))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
        
    ctx = {
        "user_id": row["id"],
        "username": row["username"],
        "status": row["status"] or "enabled",
        "session_version": row["session_version"] or 1,
        "privilege_id": row["privilege_id"],
        "privilege_name": row["privilege_name"] or "Custom",
        "is_protected": row["is_protected"] or 0,
        "system_key": row["system_key"],
        "legacy_role": row["priv_legacy"] or row["user_legacy"] or "agent",
        "user_type": row["user_type"] or "management",
        "extension_ext": row["extension_ext"],
        "permissions": set(),
        "scopes": {}
    }
    
    if ctx["privilege_id"]:
        c.execute("SELECT module, action FROM privilege_permissions WHERE privilege_id = ?", (ctx["privilege_id"],))
        ctx["permissions"] = {(r["module"], r["action"]) for r in c.fetchall()}
        
        c.execute("""
            SELECT scope_type, scope_mode,
                   COALESCE(all_data, 0) AS all_data,
                   COALESCE(all_extensions, 0) AS all_extensions,
                   COALESCE(all_queues, 0) AS all_queues,
                   COALESCE(all_ring_groups, 0) AS all_ring_groups
            FROM privilege_scope_settings WHERE privilege_id = ?
        """, (ctx["privilege_id"],))
        scopes = {}
        for r in c.fetchall():
            scopes[r["scope_type"]] = {
                "mode": r["scope_mode"],
                "items": set(),
                "all_data": bool(r["all_data"]),
                "all_extensions": bool(r["all_extensions"]),
                "all_queues": bool(r["all_queues"]),
                "all_ring_groups": bool(r["all_ring_groups"]),
                "group_items": {group: set() for group in REPORTING_SCOPE_GROUPS},
            }
            
        c.execute("SELECT scope_type, scope_id FROM privilege_scope_items WHERE privilege_id = ?", (ctx["privilege_id"],))
        for r in c.fetchall():
            st = r["scope_type"]
            if st in scopes:
                group, item = _parse_reporting_scope_item(st, r["scope_id"])
                scopes[st]["items"].add(str(item))
                scopes[st]["group_items"].setdefault(group, set()).add(str(item))
        ctx["scopes"] = scopes
        
    conn.close()
    return ctx

def get_user_scope_for_type(user_id, scope_type):
    ctx = get_user_permissions_context(user_id)
    if not ctx:
        return "none", set()
    if ctx.get("system_key") == "super_admin":
        return "all", set()
    scopes = ctx.get("scopes", {})
    if scope_type in scopes:
        s = scopes[scope_type]
        mode = s.get("mode", "none")
        if mode not in ("all", "selected", "none"):
            mode = "none"
        return mode, s.get("items", set())
    return "none", set()


def cleanup_reporting_scope_references(group, item_id):
    """Remove deleted Extension/Queue/Ring Group references from all roles."""
    group = str(group or "").strip().lower()
    item_id = str(item_id or "").strip()
    if group not in REPORTING_SCOPE_GROUPS or not item_id:
        return 0
    namespaced = _reporting_scope_item(group, item_id)
    conn = get_db()
    try:
        c = conn.cursor()
        if group == "extensions":
            c.execute("""
                DELETE FROM privilege_scope_items
                WHERE scope_id = ? OR (scope_type IN ('cdr_reports', 'call_records') AND scope_id = ?)
            """, (namespaced, item_id))
        elif group == "queues":
            c.execute("""
                DELETE FROM privilege_scope_items
                WHERE scope_id = ? OR (scope_type IN ('queue_live', 'queue_stats') AND scope_id = ?)
            """, (namespaced, item_id))
        else:
            c.execute("DELETE FROM privilege_scope_items WHERE scope_id = ?", (namespaced,))
        count = c.rowcount
        conn.commit()
        return count
    finally:
        conn.close()

# ==============================================================================
# Surveys (Customer Satisfaction)
# ==============================================================================

def get_all_surveys():
    conn = _get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM surveys ORDER BY created_at DESC")
    rows = c.fetchall()
    surveys = []
    for r in rows:
        survey = dict(r)
        c.execute("SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY question_number", (r["id"],))
        survey["questions"] = [dict(q) for q in c.fetchall()]
        surveys.append(survey)
    conn.close()
    return surveys

def get_survey(survey_id):
    conn = _get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    survey = dict(row)
    c.execute("SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY question_number", (survey_id,))
    survey["questions"] = [dict(q) for q in c.fetchall()]
    conn.close()
    return survey

def add_survey(name, recordings):
    conn = _get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO surveys (name) VALUES (?)", (name,))
    survey_id = c.lastrowid
    for i, path in enumerate(recordings, start=1):
        c.execute("INSERT INTO survey_questions (survey_id, question_number, recording_path) VALUES (?, ?, ?)",
                  (survey_id, i, path))
    conn.commit()
    conn.close()
    return survey_id

def update_survey(survey_id, name, recordings):
    conn = _get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE surveys SET name = ? WHERE id = ?", (name, survey_id))
    c.execute("DELETE FROM survey_questions WHERE survey_id = ?", (survey_id,))
    for i, path in enumerate(recordings, start=1):
        c.execute("INSERT INTO survey_questions (survey_id, question_number, recording_path) VALUES (?, ?, ?)",
                  (survey_id, i, path))
    conn.commit()
    conn.close()

def delete_survey(survey_id):
    conn = _get_db_connection()
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("DELETE FROM surveys WHERE id = ?", (survey_id,))
    conn.commit()
    conn.close()

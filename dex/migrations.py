import sqlite3
from datetime import datetime, timezone

from .constants import DEX_SCHEMA_VERSION, DEX_DRIVER_NAME, GRANDSTREAM_DRIVER_NAME


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seed_models(conn):
    vendors = {
        "FiberMe": "FIBERME",
        "Fanvil": "FANVIL",
        "Grandstream": "GRANDSTREAM",
    }
    for name, code in vendors.items():
        conn.execute(
            "INSERT OR IGNORE INTO dex_vendors (vendor_code, vendor_name, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
            (code, name, _now(), _now()),
        )

    # Only values verified by the supplied evidence are seeded.  BLF capacity
    # is deliberately NULL for both initial models until an administrator has
    # a model-specific verified definition.
    models = [
        ("FIBERME", "FAP2730P", 4, 3, "F0V730P00000.cfg", 1, 1, 1,
         "SIP/HTTPS ua-profile flow verified on firmware 2.12.21.6.1. SIP/BLF capacity supplied by the administrator; validate key behaviour on hardware before broad rollout.", 1, DEX_DRIVER_NAME),
        ("FANVIL", "X6U", None, None, "", 0, 0, 0,
         "Observed SIP ua-profile flow; account and BLF capacities require explicit model verification.", 0, DEX_DRIVER_NAME),
        ("GRANDSTREAM", "GRP2602P", 2, 0, "", 1, 1, 1,
         "HTTP ua-profile and Account 1 XML provisioning verified on GRP2602P firmware 1.0.7.66. BLF/DSS mapping is not verified.", 1, GRANDSTREAM_DRIVER_NAME),
        ("GRANDSTREAM", "GXV3350", 16, 0, "", 1, 1, 1,
         "HTTP ua-profile and alias XML provisioning verified on GXV3350 firmware 1.0.3.57. BLF/DSS mapping is not verified.", 1, GRANDSTREAM_DRIVER_NAME),
    ]
    for vendor_code, model_name, sip, blf, common, enabled, provisionable, tested, notes, tested_evidence, driver_name in models:
        vendor_id = conn.execute("SELECT id FROM dex_vendors WHERE vendor_code = ?", (vendor_code,)).fetchone()[0]
        existing = conn.execute(
            "SELECT id, verification_status, sip_account_count, blf_count, common_config_filename, enabled, provisionable, tested, notes FROM dex_models WHERE vendor_id = ? AND lower(model_name) = lower(?)",
            (vendor_id, model_name),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO dex_models
                (vendor_id, model_name, sip_account_count, blf_count,
                 common_config_filename, driver_name, enabled, provisionable,
                 tested, blf_mapping_verified, verification_status, notes,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Unverified', ?, ?, ?)""",
                (vendor_id, model_name, sip, blf, common, driver_name,
                 enabled, provisionable, tested, tested_evidence, notes, _now(), _now()),
            )
        else:
            # Never overwrite verified or manually populated capability data.
            row = dict(zip(("id", "verification_status", "sip_account_count", "blf_count", "common_config_filename", "enabled", "provisionable", "tested", "notes"), existing))
            if row["verification_status"] in ("Documentation Reviewed", "Template Reviewed", "Device Tested", "Production Verified"):
                continue
            updates = []
            values = []
            for column, value in (("sip_account_count", sip), ("blf_count", blf), ("common_config_filename", common), ("notes", notes)):
                if value not in (None, "") and row[column] in (None, ""):
                    updates.append(f"{column} = ?")
                    values.append(value)
            if updates:
                updates.append("updated_at = ?")
                values.append(_now())
                values.append(row["id"])
                conn.execute(f"UPDATE dex_models SET {', '.join(updates)} WHERE id = ?", values)


def _apply_catalog_v2(conn):
    """Fill the administrator-supplied FAP2730P BLF capability only when the
    row is still the untouched unverified seed.  A manually changed or
    verified row is never overwritten.
    """
    row = conn.execute("""SELECT m.id, m.verification_status, m.blf_count,
        m.sip_account_count, m.common_config_filename, m.notes
        FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id
        WHERE v.vendor_code = 'FIBERME' AND lower(m.model_name) = lower('FAP2730P')""").fetchone()
    if not row or row[1] != "Unverified" or row[2] is not None:
        return
    if row[3] == 4 and row[4] == "F0V730P00000.cfg":
        conn.execute("""UPDATE dex_models SET blf_count = 3, enabled = 1,
            provisionable = 1, tested = 1, blf_mapping_verified = 1,
            notes = ?, updated_at = ? WHERE id = ?""", (
            "SIP/HTTPS ua-profile flow verified on firmware 2.12.21.6.1. SIP/BLF capacity supplied by the administrator; validate key behaviour on hardware before broad rollout.", _now(), row[0]))


def _seed_permissions(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'privileges'").fetchone():
        return
    permissions = {
        "dex_phones": ("view", "add", "edit", "delete", "notify", "reboot", "autoscan"),
        "dex_models": ("view", "add", "edit", "delete"),
        "dex_config": ("view", "edit"),
    }
    for system_key, selected in (("super_admin", permissions), ("supervisor", {"dex_phones": ("view",), "dex_models": ("view",), "dex_config": ("view",)})):
        row = conn.execute("SELECT id FROM privileges WHERE system_key = ?", (system_key,)).fetchone()
        if not row:
            continue
        for module, actions in selected.items():
            for action in actions:
                conn.execute("INSERT OR IGNORE INTO privilege_permissions (privilege_id, module, action) VALUES (?, ?, ?)", (row[0], module, action))


def _apply_schema_v3(conn):
    """Remove the accidental UNIQUE(status, target_cidr) job constraint.

    A network may be scanned repeatedly.  SQLite cannot drop a table
    constraint in place, so rebuild the two DEX-owned discovery tables while
    preserving their rows and foreign-key relationship.
    """
    conn.execute("ALTER TABLE dex_discovery_results RENAME TO dex_discovery_results_v2")
    conn.execute("ALTER TABLE dex_discovery_jobs RENAME TO dex_discovery_jobs_v2")
    conn.execute("""CREATE TABLE dex_discovery_jobs_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL DEFAULT 'Pending',
        target_cidr TEXT NOT NULL,
        requested_by TEXT NOT NULL DEFAULT '',
        progress INTEGER NOT NULL DEFAULT 0,
        current_target TEXT NOT NULL DEFAULT '',
        responses_received INTEGER NOT NULL DEFAULT 0,
        phones_found INTEGER NOT NULL DEFAULT 0,
        new_devices INTEGER NOT NULL DEFAULT 0,
        updated_devices INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        lock_owner TEXT NOT NULL DEFAULT '',
        lease_expires_at TEXT
    )""")
    conn.execute("""CREATE TABLE dex_discovery_results_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL REFERENCES dex_discovery_jobs_new(id) ON DELETE CASCADE,
        ip_address TEXT NOT NULL,
        normalized_mac TEXT,
        vendor TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        firmware TEXT NOT NULL DEFAULT '',
        raw_user_agent TEXT NOT NULL DEFAULT '',
        confidence TEXT NOT NULL DEFAULT 'Unknown',
        response_code INTEGER,
        observed_at TEXT NOT NULL
    )""")
    conn.execute("""INSERT INTO dex_discovery_jobs_new
        (id, status, target_cidr, requested_by, progress, current_target,
         responses_received, phones_found, new_devices, updated_devices,
         errors, error_message, created_at, started_at, finished_at,
         lock_owner, lease_expires_at)
        SELECT id, status, target_cidr, requested_by, progress, current_target,
         responses_received, phones_found, new_devices, updated_devices,
         errors, error_message, created_at, started_at, finished_at,
         lock_owner, lease_expires_at
        FROM dex_discovery_jobs_v2""")
    conn.execute("""INSERT INTO dex_discovery_results_new
        (id, job_id, ip_address, normalized_mac, vendor, model, firmware,
         raw_user_agent, confidence, response_code, observed_at)
        SELECT id, job_id, ip_address, normalized_mac, vendor, model, firmware,
         raw_user_agent, confidence, response_code, observed_at
        FROM dex_discovery_results_v2""")
    conn.execute("DROP TABLE dex_discovery_results_v2")
    conn.execute("DROP TABLE dex_discovery_jobs_v2")
    conn.execute("ALTER TABLE dex_discovery_jobs_new RENAME TO dex_discovery_jobs")
    conn.execute("ALTER TABLE dex_discovery_results_new RENAME TO dex_discovery_results")
    conn.execute("CREATE INDEX idx_dex_discovery_results_job ON dex_discovery_results(job_id, ip_address)")


def _apply_schema_v4(conn):
    """Normalize devices whose saved error was hidden by a later discovery."""
    conn.execute("""UPDATE dex_devices
        SET provision_status = 'Failed', updated_at = ?
        WHERE last_error <> '' AND provision_status IN ('Unknown Model', 'Model Defined')""", (_now(),))


def _apply_schema_v5(conn):
    """Add one bounded post-download registration settle delay."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(dex_global_config)").fetchall()}
    if "registration_check_delay" not in columns:
        conn.execute("ALTER TABLE dex_global_config ADD COLUMN registration_check_delay REAL NOT NULL DEFAULT 3.0")


def _apply_schema_v6(conn):
    """Add an explicit LDAP source selector without changing existing values."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(dex_global_config)").fetchall()}
    if "ldap_use_rcm_settings" not in columns:
        conn.execute("ALTER TABLE dex_global_config ADD COLUMN ldap_use_rcm_settings INTEGER NOT NULL DEFAULT 0 CHECK (ldap_use_rcm_settings IN (0,1))")


def _apply_schema_v7(conn):
    """Add the cleartext HTTP listener used by Grandstream phones."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(dex_global_config)").fetchall()}
    if "provisioning_http_port" not in columns:
        conn.execute("ALTER TABLE dex_global_config ADD COLUMN provisioning_http_port INTEGER NOT NULL DEFAULT 8091")
    _seed_models(conn)


def _apply_schema_v8(conn):
    """Promote inventory rows whose defined model is fully provisionable.

    Discovery used to leave these rows at ``Model Defined`` even when the
    model was enabled and had complete SIP/BLF capabilities.  Keep all later
    operational statuses untouched; this only repairs the initial states.
    """
    conn.execute("""UPDATE dex_devices
        SET provision_status = 'Ready for Configuration', updated_at = ?
        WHERE provision_status IN ('Unknown Model', 'Model Defined')
          AND model_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM dex_models m
              WHERE m.id = dex_devices.model_id
                AND m.enabled = 1
                AND m.provisionable = 1
                AND m.sip_account_count IS NOT NULL
                AND m.blf_count IS NOT NULL
          )""", (_now(),))


def _apply_schema_v9(conn):
    """Record the verified eight-key BLF layout for the GRP2602P."""
    conn.execute("""UPDATE dex_models
        SET blf_count = 8,
            blf_mapping_verified = 1,
            notes = ?,
            updated_at = ?
        WHERE id IN (
            SELECT m.id FROM dex_models m
            JOIN dex_vendors v ON v.id = m.vendor_id
            WHERE v.vendor_code = 'GRANDSTREAM'
              AND lower(m.model_name) = lower('GRP2602P')
              AND m.blf_count = 0
        )""", (
        "HTTP ua-profile and Account 1 XML provisioning verified on GRP2602P firmware 1.0.7.66. The model exposes 8 verified BLF keys using pks.vpk.N XML items.",
        _now(),
    ))


def _apply_schema_v10(conn):
    """Persist a Grandstream PnP Contact for phones not yet SIP-registered."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(dex_devices)").fetchall()}
    if "pnp_contact_ip" not in columns:
        conn.execute("ALTER TABLE dex_devices ADD COLUMN pnp_contact_ip TEXT NOT NULL DEFAULT ''")
    if "pnp_contact_port" not in columns:
        conn.execute("ALTER TABLE dex_devices ADD COLUMN pnp_contact_port INTEGER")
    if "pnp_contact_seen_at" not in columns:
        conn.execute("ALTER TABLE dex_devices ADD COLUMN pnp_contact_seen_at TEXT")


def run_migrations(db_path):
    """Apply DEX-owned schema atomically and idempotently."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS dex_schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM dex_schema_versions").fetchone()[0]
        if current < 1:
            schema_sql = """
            CREATE TABLE IF NOT EXISTS dex_vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                vendor_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dex_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL REFERENCES dex_vendors(id) ON DELETE RESTRICT,
                model_name TEXT NOT NULL COLLATE NOCASE,
                sip_account_count INTEGER CHECK (sip_account_count IS NULL OR sip_account_count >= 1),
                blf_count INTEGER CHECK (blf_count IS NULL OR blf_count >= 0),
                common_config_filename TEXT NOT NULL DEFAULT '',
                driver_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
                provisionable INTEGER NOT NULL DEFAULT 0 CHECK (provisionable IN (0,1)),
                tested INTEGER NOT NULL DEFAULT 0 CHECK (tested IN (0,1)),
                blf_mapping_verified INTEGER NOT NULL DEFAULT 0 CHECK (blf_mapping_verified IN (0,1)),
                verification_status TEXT NOT NULL DEFAULT 'Unverified',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(vendor_id, model_name)
            );
            CREATE INDEX IF NOT EXISTS idx_dex_models_vendor ON dex_models(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_dex_models_status ON dex_models(enabled, provisionable, tested);
            CREATE TABLE IF NOT EXISTS dex_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_mac TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_mac TEXT NOT NULL,
                ip_address TEXT,
                vendor TEXT NOT NULL DEFAULT '',
                detected_model TEXT NOT NULL DEFAULT '',
                model_id INTEGER REFERENCES dex_models(id) ON DELETE RESTRICT,
                firmware TEXT NOT NULL DEFAULT '',
                raw_user_agent TEXT NOT NULL DEFAULT '',
                mac_source TEXT NOT NULL DEFAULT '',
                last_seen TEXT,
                provision_status TEXT NOT NULL DEFAULT 'Unknown Model',
                last_notify_at TEXT,
                last_success_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                last_failure_stage TEXT NOT NULL DEFAULT '',
                last_requested_filename TEXT NOT NULL DEFAULT '',
                last_http_status INTEGER,
                last_sip_status INTEGER,
                last_registered_extension TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dex_devices_ip ON dex_devices(ip_address);
            CREATE INDEX IF NOT EXISTS idx_dex_devices_vendor_model ON dex_devices(vendor, detected_model);
            CREATE INDEX IF NOT EXISTS idx_dex_devices_seen ON dex_devices(last_seen);
            CREATE TABLE IF NOT EXISTS dex_device_ip_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES dex_devices(id) ON DELETE CASCADE,
                ip_address TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_dex_ip_history_device ON dex_device_ip_history(device_id, observed_at);
            CREATE TABLE IF NOT EXISTS dex_device_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES dex_devices(id) ON DELETE CASCADE,
                account_index INTEGER NOT NULL CHECK (account_index >= 1),
                extension TEXT,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(device_id, account_index)
            );
            CREATE INDEX IF NOT EXISTS idx_dex_accounts_extension ON dex_device_accounts(extension);
            CREATE TABLE IF NOT EXISTS dex_device_blf_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES dex_devices(id) ON DELETE CASCADE,
                key_index INTEGER NOT NULL CHECK (key_index >= 1),
                enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
                semantic_type TEXT NOT NULL DEFAULT 'None',
                title TEXT NOT NULL DEFAULT '',
                value TEXT NOT NULL DEFAULT '',
                pickup TEXT NOT NULL DEFAULT '',
                account_index INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(device_id, key_index)
            );
            CREATE TABLE IF NOT EXISTS dex_global_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provisioning_enabled INTEGER NOT NULL DEFAULT 1,
                provisioning_ip TEXT NOT NULL DEFAULT '',
                provisioning_port INTEGER NOT NULL DEFAULT 8090,
                provisioning_http_port INTEGER NOT NULL DEFAULT 8091,
                provisioning_path TEXT NOT NULL DEFAULT 'DEXPhone',
                notify_source_port INTEGER NOT NULL DEFAULT 0,
                notify_timeout REAL NOT NULL DEFAULT 3.0,
                notify_user_agent TEXT NOT NULL DEFAULT 'RCM7021',
                sntp_enabled INTEGER NOT NULL DEFAULT 1,
                primary_ntp TEXT NOT NULL DEFAULT '',
                secondary_ntp TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT '',
                timezone_name TEXT NOT NULL DEFAULT '',
                date_format TEXT NOT NULL DEFAULT '',
                time_format TEXT NOT NULL DEFAULT '',
                date_separator TEXT NOT NULL DEFAULT '',
                mmi_username TEXT NOT NULL DEFAULT '',
                mmi_password_encrypted BLOB,
                ldap_enabled INTEGER NOT NULL DEFAULT 0,
                ldap_title TEXT NOT NULL DEFAULT 'FCM',
                ldap_server TEXT NOT NULL DEFAULT '',
                ldap_port INTEGER NOT NULL DEFAULT 389,
                ldap_base TEXT NOT NULL DEFAULT '',
                ldap_use_ssl INTEGER NOT NULL DEFAULT 0,
                ldap_version INTEGER NOT NULL DEFAULT 3,
                ldap_authenticate INTEGER,
                ldap_username TEXT NOT NULL DEFAULT '',
                ldap_password_encrypted BLOB,
                ldap_calling_line INTEGER,
                ldap_bind_line INTEGER,
                ldap_in_call_search INTEGER NOT NULL DEFAULT 1,
                ldap_out_call_search INTEGER NOT NULL DEFAULT 1,
                ldap_tel_attr TEXT NOT NULL DEFAULT 'telephoneNumber',
                ldap_mobile_attr TEXT NOT NULL DEFAULT 'mobile',
                ldap_other_attr TEXT NOT NULL DEFAULT 'other',
                ldap_name_attr TEXT NOT NULL DEFAULT 'cn sn ou',
                ldap_sort_attr TEXT NOT NULL DEFAULT 'cn',
                ldap_displayname TEXT NOT NULL DEFAULT 'cn',
                ldap_number_filter TEXT NOT NULL DEFAULT '(|(telephoneNumber=%)(mobile=%)(other=%))',
                ldap_name_filter TEXT NOT NULL DEFAULT '(|(cn=%)(sn=%))',
                ldap_max_hits INTEGER NOT NULL DEFAULT 50,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dex_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER REFERENCES dex_devices(id) ON DELETE SET NULL,
                operation_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                started_at TEXT,
                completed_at TEXT,
                requested_by TEXT NOT NULL DEFAULT '',
                error_stage TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                requested_url TEXT NOT NULL DEFAULT '',
                expected_filename TEXT NOT NULL DEFAULT '',
                sent_at TEXT,
                sip_response_at TEXT,
                sip_status INTEGER,
                http_request_at TEXT,
                http_path TEXT NOT NULL DEFAULT '',
                http_status INTEGER,
                http_bytes INTEGER,
                registration_result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dex_operations_status ON dex_operations(status, operation_type);
            CREATE INDEX IF NOT EXISTS idx_dex_operations_device ON dex_operations(device_id, created_at);
            CREATE TABLE IF NOT EXISTS dex_operation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id INTEGER NOT NULL REFERENCES dex_operations(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                details_json_sanitized TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS dex_generated_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES dex_devices(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                published_at TEXT,
                active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0,1)),
                archive_path TEXT NOT NULL DEFAULT '',
                UNIQUE(device_id, sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_dex_configs_active ON dex_generated_configs(device_id, active);
            CREATE TABLE IF NOT EXISTS dex_discovery_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL DEFAULT 'Pending',
                target_cidr TEXT NOT NULL,
                requested_by TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                current_target TEXT NOT NULL DEFAULT '',
                responses_received INTEGER NOT NULL DEFAULT 0,
                phones_found INTEGER NOT NULL DEFAULT 0,
                new_devices INTEGER NOT NULL DEFAULT 0,
                updated_devices INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                lock_owner TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT,
                UNIQUE(status, target_cidr)
            );
            CREATE TABLE IF NOT EXISTS dex_discovery_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES dex_discovery_jobs(id) ON DELETE CASCADE,
                ip_address TEXT NOT NULL,
                normalized_mac TEXT,
                vendor TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                firmware TEXT NOT NULL DEFAULT '',
                raw_user_agent TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT 'Unknown',
                response_code INTEGER,
                observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dex_discovery_results_job ON dex_discovery_results(job_id, ip_address);
            """
            # sqlite3.executescript commits an active transaction before it
            # runs.  Execute this DEX-owned DDL statement-by-statement so a
            # failure rolls the complete migration back.
            for statement in schema_sql.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            _seed_models(conn)
            conn.execute("INSERT INTO dex_global_config (id, created_at, updated_at) VALUES (1, ?, ?)", (_now(), _now()))
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (1, ?)", (_now(),))
            current = 1
        if current < 2:
            _apply_catalog_v2(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (2, ?)", (_now(),))
            current = 2
        if current < 3:
            _apply_schema_v3(conn)
            # Do not leave a worker that died under the old schema looking
            # permanently active.  Only expired leases are recoverable here.
            conn.execute("""UPDATE dex_discovery_jobs
                SET status = 'Failed', finished_at = COALESCE(finished_at, ?),
                    error_message = CASE WHEN error_message = '' THEN 'Discovery worker lease expired during schema migration.' ELSE error_message END
                WHERE status = 'Running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""", (_now(), _now()))
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (3, ?)", (_now(),))
            current = 3
        if current < 4:
            _apply_schema_v4(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (4, ?)", (_now(),))
            current = 4
        if current < 5:
            _apply_schema_v5(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (5, ?)", (_now(),))
            current = 5
        if current < 6:
            _apply_schema_v6(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (6, ?)", (_now(),))
            current = 6
        if current < 7:
            _apply_schema_v7(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (7, ?)", (_now(),))
            current = 7
        if current < 8:
            _apply_schema_v8(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (8, ?)", (_now(),))
            current = 8
        if current < 9:
            _apply_schema_v9(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (9, ?)", (_now(),))
            current = 9
        if current < 10:
            _apply_schema_v10(conn)
            conn.execute("INSERT INTO dex_schema_versions (version, applied_at) VALUES (10, ?)", (_now(),))
            current = 10
        _seed_permissions(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

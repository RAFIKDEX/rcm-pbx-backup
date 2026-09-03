import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .constants import DEVICE_STATUSES, DEX_DRIVER_NAME, GRANDSTREAM_DRIVER_NAME
from .validators import display_mac, normalize_mac, validate_ip


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def row_dict(row):
    return dict(row) if row else None


def _sanitize_event_details(value):
    secret_words = ("password", "secret", "authorization", "cookie", "token")
    if isinstance(value, dict):
        return {key: ("******" if any(word in str(key).lower() for word in secret_words) else _sanitize_event_details(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_event_details(item) for item in value]
    return value


class DexRepository:
    def __init__(self, db_path):
        self.db_path = db_path

    def _conn(self):
        return connect(self.db_path)

    def get_config(self):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM dex_global_config WHERE id = 1").fetchone()
            return row_dict(row) or {}

    def save_config(self, values):
        allowed = {
            "provisioning_enabled", "provisioning_ip", "provisioning_port", "provisioning_http_port", "provisioning_path",
            "notify_source_port", "notify_timeout", "notify_user_agent", "registration_check_delay", "sntp_enabled",
            "primary_ntp", "secondary_ntp", "timezone", "timezone_name", "date_format",
            "time_format", "date_separator", "mmi_username", "mmi_password_encrypted",
            "ldap_enabled", "ldap_use_rcm_settings", "ldap_title", "ldap_server", "ldap_port", "ldap_base",
            "ldap_use_ssl", "ldap_version", "ldap_authenticate", "ldap_username",
            "ldap_password_encrypted", "ldap_calling_line", "ldap_bind_line",
            "ldap_in_call_search", "ldap_out_call_search", "ldap_tel_attr", "ldap_mobile_attr",
            "ldap_other_attr", "ldap_name_attr", "ldap_sort_attr", "ldap_displayname",
            "ldap_number_filter", "ldap_name_filter", "ldap_max_hits",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return self.get_config()
        values["updated_at"] = now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._conn() as conn:
            conn.execute(f"UPDATE dex_global_config SET {assignments} WHERE id = 1", tuple(values.values()))
            conn.commit()
            return row_dict(conn.execute("SELECT * FROM dex_global_config WHERE id = 1").fetchone())

    def list_models(self, search="", vendor="", enabled="", tested="", provisionable="", page=1, per_page=20):
        where = ["1=1"]
        params = []
        if search:
            value = f"%{search}%"
            where.append("(m.model_name LIKE ? OR v.vendor_name LIKE ? OR v.vendor_code LIKE ?)")
            params.extend([value, value, value])
        if vendor:
            where.append("v.vendor_code = ?")
            params.append(vendor.upper())
        if enabled in ("0", "1"):
            where.append("m.enabled = ?")
            params.append(int(enabled))
        if tested in ("0", "1"):
            where.append("m.tested = ?")
            params.append(int(tested))
        if provisionable in ("0", "1"):
            where.append("m.provisionable = ?")
            params.append(int(provisionable))
        clause = " AND ".join(where)
        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE {clause}", params).fetchone()[0]
            rows = conn.execute(
                f"""SELECT m.*, v.vendor_code, v.vendor_name,
                    (SELECT COUNT(*) FROM dex_devices d WHERE d.model_id = m.id) AS devices_count
                    FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id
                    WHERE {clause} ORDER BY v.vendor_name, m.model_name LIMIT ? OFFSET ?""",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], total

    def get_model(self, model_id):
        with self._conn() as conn:
            row = conn.execute("SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE m.id = ?", (model_id,)).fetchone()
            return row_dict(row)

    def get_model_by_name(self, vendor, model_name):
        with self._conn() as conn:
            row = conn.execute("SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE v.vendor_code = ? AND lower(m.model_name) = lower(?)", (str(vendor).upper(), model_name)).fetchone()
            return row_dict(row)

    def ensure_discovered_model(self, vendor, model_name, raw_user_agent=""):
        """Create a safe draft model definition from verified discovery data.

        Discovery may prove the vendor/model identity, but it must not infer
        account or BLF capacity.  The resulting row is intentionally disabled
        and non-provisionable until an administrator completes its definition.
        """
        vendor_code = str(vendor or "").strip().upper()
        model_name = str(model_name or "").strip()
        if vendor_code not in {"FIBERME", "FANVIL", "GRANDSTREAM"} or not model_name:
            return None
        timestamp = now()
        note = "Discovered by SIP OPTIONS; SIP account and BLF/DSS capabilities require administrator verification."
        if raw_user_agent:
            note += f" Raw User-Agent: {raw_user_agent[:240]}"
        with self._conn() as conn:
            vendor_row = conn.execute("SELECT id FROM dex_vendors WHERE vendor_code = ?", (vendor_code,)).fetchone()
            if not vendor_row:
                return None
            existing = conn.execute(
                "SELECT id FROM dex_models WHERE vendor_id = ? AND lower(model_name) = lower(?)",
                (vendor_row[0], model_name),
            ).fetchone()
            if existing:
                row = conn.execute("SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE m.id = ?", (existing[0],)).fetchone()
                return dict(row)
            conn.execute("""INSERT INTO dex_models
                (vendor_id, model_name, sip_account_count, blf_count,
                 common_config_filename, driver_name, enabled, provisionable,
                 tested, blf_mapping_verified, verification_status, notes,
                 created_at, updated_at)
                VALUES (?, ?, NULL, NULL, '', ?, 0, 0, 0, 0, 'Unverified', ?, ?, ?)""",
                (vendor_row[0], model_name, GRANDSTREAM_DRIVER_NAME if vendor_code == "GRANDSTREAM" else DEX_DRIVER_NAME, note, timestamp, timestamp),
            )
            conn.commit()
            row = conn.execute("SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE m.id = last_insert_rowid()").fetchone()
            return dict(row)

    def enabled_models(self, vendor=None):
        with self._conn() as conn:
            params = []
            where = ["m.enabled = 1"]
            if vendor:
                where.append("v.vendor_code = ?")
                params.append(str(vendor).upper())
            rows = conn.execute(f"SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE {' AND '.join(where)} ORDER BY m.model_name", params).fetchall()
            return [dict(row) for row in rows]

    def discovered_undefined_models(self):
        """Return supported vendor/model identities found in inventory only.

        Discovery proves an identity, not capabilities.  These entries are
        therefore offered by Add as inventory-only choices and never receive
        a model_id or provisioning controls until an administrator defines
        them in DEX Model.
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT
                    CASE UPPER(TRIM(d.vendor))
                        WHEN 'FIBERME' THEN 'FIBERME'
                        WHEN 'FANVIL' THEN 'FANVIL'
                        WHEN 'GRANDSTREAM' THEN 'GRANDSTREAM'
                    END AS vendor_code,
                    CASE UPPER(TRIM(d.vendor))
                        WHEN 'FIBERME' THEN 'FiberMe'
                        WHEN 'FANVIL' THEN 'Fanvil'
                        WHEN 'GRANDSTREAM' THEN 'Grandstream'
                    END AS vendor_name,
                    TRIM(d.detected_model) AS model_name
                FROM dex_devices d
                LEFT JOIN dex_vendors v
                    ON UPPER(v.vendor_code) = UPPER(TRIM(d.vendor))
                LEFT JOIN dex_models m
                    ON m.vendor_id = v.id
                   AND lower(m.model_name) = lower(TRIM(d.detected_model))
                WHERE UPPER(TRIM(d.vendor)) IN ('FIBERME', 'FANVIL', 'GRANDSTREAM')
                  AND TRIM(d.detected_model) <> ''
                  AND m.id IS NULL
                ORDER BY vendor_name, model_name
            """).fetchall()
            return [dict(row) for row in rows]

    def save_model(self, values, model_id=None):
        required = ("vendor_code", "model_name", "driver_name")
        for key in required:
            if not values.get(key):
                raise ValueError(f"{key.replace('_', ' ').title()} is required.")
        timestamp = now()
        with self._conn() as conn:
            vendor = conn.execute("SELECT id FROM dex_vendors WHERE vendor_code = ?", (values["vendor_code"].upper(),)).fetchone()
            if not vendor:
                raise ValueError("Unsupported DEX vendor.")
            vendor_id = vendor[0]
            duplicate = conn.execute("SELECT id FROM dex_models WHERE vendor_id = ? AND lower(model_name) = lower(?) AND id != COALESCE(?, 0)", (vendor_id, values["model_name"].strip(), model_id)).fetchone()
            if duplicate:
                raise ValueError("That vendor/model combination already exists.")
            if model_id:
                sets = ["vendor_id = ?", "model_name = ?", "sip_account_count = ?", "blf_count = ?", "common_config_filename = ?", "driver_name = ?", "enabled = ?", "provisionable = ?", "tested = ?", "blf_mapping_verified = ?", "notes = ?", "updated_at = ?"]
                vals = [vendor_id, values["model_name"].strip(), values.get("sip_account_count"), values.get("blf_count"), values.get("common_config_filename", ""), values["driver_name"], int(values.get("enabled", 0)), int(values.get("provisionable", 0)), int(values.get("tested", 0)), int(values.get("blf_mapping_verified", 0)), values.get("notes", ""), timestamp, model_id]
                conn.execute(f"UPDATE dex_models SET {', '.join(f'{s} = ?' if ' = ?' not in s else s for s in sets)} WHERE id = ?", vals)
                saved_model_id = model_id
            else:
                conn.execute("""INSERT INTO dex_models
                    (vendor_id, model_name, sip_account_count, blf_count,
                     common_config_filename, driver_name, enabled, provisionable,
                     tested, blf_mapping_verified, verification_status, notes,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Unverified', ?, ?, ?)""",
                    (vendor_id, values["model_name"].strip(), values.get("sip_account_count"), values.get("blf_count"), values.get("common_config_filename", ""), values["driver_name"], int(values.get("enabled", 0)), int(values.get("provisionable", 0)), int(values.get("tested", 0)), int(values.get("blf_mapping_verified", 0)), values.get("notes", ""), timestamp, timestamp))
                saved_model_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            self._promote_ready_devices(conn, saved_model_id, timestamp)
            conn.commit()
            return row_dict(conn.execute("SELECT m.*, v.vendor_code, v.vendor_name FROM dex_models m JOIN dex_vendors v ON v.id = m.vendor_id WHERE m.id = COALESCE(?, last_insert_rowid())", (model_id,)).fetchone())

    def delete_model(self, model_id):
        with self._conn() as conn:
            model = conn.execute("SELECT provisionable, sip_account_count, blf_count FROM dex_models WHERE id = ?", (model_id,)).fetchone()
            if not model:
                return
            verified_provisionable = bool(model["provisionable"] and model["sip_account_count"] is not None and model["blf_count"] is not None)
            if verified_provisionable and conn.execute("SELECT 1 FROM dex_devices WHERE model_id = ? LIMIT 1", (model_id,)).fetchone():
                raise ValueError("This model is assigned to a DEX device and cannot be deleted.")
            # Inventory-only/unverified models are safe to remove. Keep the
            # discovered devices, but detach them so the FK remains valid and
            # they can be assigned a corrected model later.
            conn.execute(
                "UPDATE dex_devices SET model_id = NULL, provision_status = 'Unknown Model', updated_at = ? WHERE model_id = ?",
                (now(), model_id),
            )
            conn.execute("DELETE FROM dex_models WHERE id = ?", (model_id,))
            conn.commit()

    def toggle_model(self, model_id, enabled):
        with self._conn() as conn:
            timestamp = now()
            conn.execute("UPDATE dex_models SET enabled = ?, updated_at = ? WHERE id = ?", (int(enabled), timestamp, model_id))
            if enabled:
                self._promote_ready_devices(conn, model_id, timestamp)
            conn.commit()

    @staticmethod
    def _promote_ready_devices(conn, model_id, timestamp):
        conn.execute("""UPDATE dex_devices
            SET provision_status = 'Ready for Configuration', updated_at = ?
            WHERE model_id = ?
              AND provision_status IN ('Unknown Model', 'Model Defined')
              AND EXISTS (
                  SELECT 1 FROM dex_models m
                  WHERE m.id = dex_devices.model_id
                    AND m.enabled = 1
                    AND m.provisionable = 1
                    AND m.sip_account_count IS NOT NULL
                    AND m.blf_count IS NOT NULL
              )""", (timestamp, model_id))

    def list_devices(self, search="", page=1, per_page=20):
        where = ["UPPER(TRIM(COALESCE(d.vendor, ''))) IN ('FIBERME', 'FANVIL', 'GRANDSTREAM')"]
        params = []
        if search:
            value = f"%{search}%"
            where.append("(d.normalized_mac LIKE ? OR d.ip_address LIKE ? OR d.vendor LIKE ? OR d.detected_model LIKE ? OR d.firmware LIKE ? OR d.last_registered_extension LIKE ? OR EXISTS (SELECT 1 FROM dex_device_accounts sa WHERE sa.device_id = d.id AND sa.extension LIKE ?))")
            params.extend([value] * 7)
        clause = " AND ".join(where)
        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM dex_devices d WHERE {clause}", params).fetchone()[0]
            rows = conn.execute(f"""SELECT d.*, m.model_name AS defined_model, m.sip_account_count, m.blf_count,
                m.enabled AS model_enabled, m.provisionable, m.tested, m.blf_mapping_verified,
                GROUP_CONCAT(CASE WHEN a.enabled = 1 THEN a.extension END) AS extensions
                FROM dex_devices d LEFT JOIN dex_models m ON m.id = d.model_id
                LEFT JOIN dex_device_accounts a ON a.device_id = d.id
                WHERE {clause} GROUP BY d.id ORDER BY COALESCE(d.last_seen, d.created_at) DESC
                LIMIT ? OFFSET ?""", params + [per_page, (page - 1) * per_page]).fetchall()
            return [dict(row) for row in rows], total

    def get_device(self, device_id):
        with self._conn() as conn:
            row = conn.execute("SELECT d.*, m.model_name AS defined_model, m.sip_account_count, m.blf_count, m.enabled AS model_enabled, m.provisionable, m.tested, m.blf_mapping_verified, v.vendor_code, v.vendor_name FROM dex_devices d LEFT JOIN dex_models m ON m.id = d.model_id LEFT JOIN dex_vendors v ON v.id = m.vendor_id WHERE d.id = ?", (device_id,)).fetchone()
            if not row:
                return None
            device = dict(row)
            device["accounts"] = [dict(item) for item in conn.execute("SELECT * FROM dex_device_accounts WHERE device_id = ? ORDER BY account_index", (device_id,)).fetchall()]
            device["blf_keys"] = [dict(item) for item in conn.execute("SELECT * FROM dex_device_blf_keys WHERE device_id = ? ORDER BY key_index", (device_id,)).fetchall()]
            device["operations"] = [dict(item) for item in conn.execute("SELECT * FROM dex_operations WHERE device_id = ? ORDER BY id DESC LIMIT 20", (device_id,)).fetchall()]
            return device

    def get_operation(self, operation_id):
        with self._conn() as conn:
            row = conn.execute("""SELECT o.*, d.display_mac, d.ip_address, d.vendor,
                d.detected_model FROM dex_operations o LEFT JOIN dex_devices d
                ON d.id = o.device_id WHERE o.id = ?""", (operation_id,)).fetchone()
            if not row:
                return None
            operation = dict(row)
            operation["events"] = [dict(item) for item in conn.execute(
                "SELECT * FROM dex_operation_events WHERE operation_id = ? ORDER BY id", (operation_id,)
            ).fetchall()]
            return operation

    def find_extension_conflicts(self, extensions, device_id):
        values = sorted({str(value).strip() for value in extensions if str(value).strip()})
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        with self._conn() as conn:
            rows = conn.execute(f"""SELECT a.extension, d.id, d.display_mac
                FROM dex_device_accounts a JOIN dex_devices d ON d.id = a.device_id
                WHERE a.enabled = 1 AND a.extension IN ({placeholders}) AND d.id != ?
                ORDER BY a.extension, d.id""", values + [device_id]).fetchall()
            return [dict(row) for row in rows]

    def provisionable_devices(self):
        with self._conn() as conn:
            rows = conn.execute("""SELECT d.id FROM dex_devices d
                JOIN dex_models m ON m.id = d.model_id
                WHERE m.enabled = 1 AND m.provisionable = 1
                  AND m.sip_account_count IS NOT NULL AND m.blf_count IS NOT NULL
                ORDER BY d.id""").fetchall()
            return [self.get_device(row[0]) for row in rows]

    def get_device_by_mac(self, normalized_mac):
        normalized = normalize_mac(normalized_mac)
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM dex_devices WHERE normalized_mac = ? COLLATE NOCASE", (normalized,)).fetchone()
            return self.get_device(row["id"]) if row else None

    def save_pnp_contact(self, device_id, contact_ip, contact_port):
        """Remember the unregistered Grandstream Contact learned by PnP."""
        ip_value = validate_ip(contact_ip, allow_blank=False)
        port = int(contact_port)
        if not (1 <= port <= 65535):
            raise ValueError("Invalid PnP Contact port.")
        with self._conn() as conn:
            timestamp = now()
            conn.execute(
                "UPDATE dex_devices SET pnp_contact_ip = ?, pnp_contact_port = ?, pnp_contact_seen_at = ?, updated_at = ? WHERE id = ?",
                (ip_value, port, timestamp, timestamp, int(device_id)),
            )
            conn.commit()

    def get_pnp_contact(self, device_id):
        with self._conn() as conn:
            row = conn.execute("SELECT pnp_contact_ip, pnp_contact_port, pnp_contact_seen_at FROM dex_devices WHERE id = ?", (int(device_id),)).fetchone()
            return dict(row) if row else None


    def upsert_device(self, values, source="manual", conn=None):
        normalized = normalize_mac(values["normalized_mac"])
        ip_value = validate_ip(values.get("ip_address"), allow_blank=True)
        own = conn is None
        conn = conn or self._conn()
        try:
            timestamp = now()
            model_ready = False
            model_id = values.get("model_id")
            if model_id:
                model = conn.execute("""SELECT enabled, provisionable,
                    sip_account_count, blf_count FROM dex_models WHERE id = ?""", (model_id,)).fetchone()
                model_ready = bool(model and model[0] and model[1] and model[2] is not None and model[3] is not None)
            existing = conn.execute("SELECT * FROM dex_devices WHERE normalized_mac = ? COLLATE NOCASE", (normalized,)).fetchone()
            if existing:
                old_ip = existing["ip_address"]
                conn.execute("""UPDATE dex_devices SET display_mac = ?, ip_address = ?, vendor = ?, detected_model = ?, model_id = ?, firmware = ?, raw_user_agent = ?, mac_source = ?, last_seen = ?, updated_at = ? WHERE id = ?""", (display_mac(normalized), ip_value, values.get("vendor", ""), values.get("detected_model", ""), values.get("model_id"), values.get("firmware", ""), values.get("raw_user_agent", ""), values.get("mac_source", source), timestamp, timestamp, existing["id"]))
                if ip_value and ip_value != old_ip:
                    conn.execute("INSERT INTO dex_device_ip_history (device_id, ip_address, observed_at, source) VALUES (?, ?, ?, ?)", (existing["id"], ip_value, timestamp, source))
                device_id = existing["id"]
                if model_ready and existing["provision_status"] in ("Unknown Model", "Model Defined"):
                    conn.execute("UPDATE dex_devices SET provision_status = 'Ready for Configuration', updated_at = ? WHERE id = ?", (timestamp, device_id))
            else:
                status = values.get("provision_status") or ("Model Defined" if model_id else "Unknown Model")
                if model_ready and status in ("Unknown Model", "Model Defined"):
                    status = "Ready for Configuration"
                cur = conn.execute("""INSERT INTO dex_devices
                    (normalized_mac, display_mac, ip_address, vendor, detected_model,
                     model_id, firmware, raw_user_agent, mac_source, last_seen,
                     provision_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (normalized, display_mac(normalized), ip_value, values.get("vendor", ""), values.get("detected_model", ""), model_id, values.get("firmware", ""), values.get("raw_user_agent", ""), values.get("mac_source", source), timestamp, status, timestamp, timestamp))
                device_id = cur.lastrowid
                if ip_value:
                    conn.execute("INSERT INTO dex_device_ip_history (device_id, ip_address, observed_at, source) VALUES (?, ?, ?, ?)", (device_id, ip_value, timestamp, source))
            if own:
                conn.commit()
            return device_id
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()

    def save_assignments(self, device_id, accounts, blf_keys):
        with self._conn() as conn:
            device = conn.execute("SELECT d.*, m.sip_account_count, m.blf_count, m.provisionable FROM dex_devices d LEFT JOIN dex_models m ON m.id = d.model_id WHERE d.id = ?", (device_id,)).fetchone()
            if not device:
                raise ValueError("Device not found.")
            if not device["provisionable"] or device["sip_account_count"] is None:
                raise ValueError("Model is not provisionable and does not have a verified SIP account definition.")
            if len(accounts) != device["sip_account_count"]:
                raise ValueError("Submitted SIP account count does not match the model definition.")
            if device["blf_count"] is not None and len(blf_keys) != device["blf_count"]:
                raise ValueError("Submitted BLF count does not match the model definition.")
            expected_accounts = set(range(1, int(device["sip_account_count"]) + 1))
            account_indexes = [int(item.get("account_index")) for item in accounts]
            if set(account_indexes) != expected_accounts or len(account_indexes) != len(set(account_indexes)):
                raise ValueError("Invalid SIP account slot sequence.")
            if device["blf_count"] is not None:
                expected_keys = set(range(1, int(device["blf_count"]) + 1))
                key_indexes = [int(item.get("key_index")) for item in blf_keys]
                if set(key_indexes) != expected_keys or len(key_indexes) != len(set(key_indexes)):
                    raise ValueError("Invalid BLF/DSS key slot sequence.")
            from .constants import SEMANTIC_KEY_TYPES
            extensions = []
            for item in accounts:
                extension = str(item.get("extension") or "").strip()
                if item.get("enabled"):
                    if not extension:
                        raise ValueError(f"Account {item['account_index']} is enabled but has no extension.")
                    from .rcm_data import get_extension
                    record = get_extension(extension)
                    if not record or not int(record.get("enabled", 0)):
                        raise ValueError(f"Extension {extension} is not an enabled RCM extension.")
                    extensions.append(extension)
            if len(extensions) != len(set(extensions)):
                raise ValueError("An extension cannot be assigned to two accounts on the same phone.")
            max_account = int(device["sip_account_count"])
            for item in blf_keys:
                semantic_type = str(item.get("semantic_type") or "None")
                if semantic_type not in SEMANTIC_KEY_TYPES:
                    raise ValueError(f"Unsupported BLF/DSS type: {semantic_type}.")
                account_index = item.get("account_index")
                if account_index not in (None, ""):
                    try:
                        account_index = int(account_index)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("BLF account selection is invalid.") from exc
                    if not 1 <= account_index <= max_account:
                        raise ValueError("BLF account selection exceeds the model account count.")
            conn.execute("DELETE FROM dex_device_accounts WHERE device_id = ?", (device_id,))
            conn.execute("DELETE FROM dex_device_blf_keys WHERE device_id = ?", (device_id,))
            timestamp = now()
            for item in accounts:
                conn.execute("INSERT INTO dex_device_accounts (device_id, account_index, extension, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (device_id, int(item["account_index"]), item.get("extension") or None, int(bool(item.get("enabled"))), timestamp, timestamp))
            for item in blf_keys:
                conn.execute("INSERT INTO dex_device_blf_keys (device_id, key_index, enabled, semantic_type, title, value, pickup, account_index, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (device_id, int(item["key_index"]), int(bool(item.get("enabled"))), item.get("semantic_type", "None"), item.get("title", ""), item.get("value", ""), item.get("pickup", ""), item.get("account_index"), timestamp, timestamp))
            conn.execute("UPDATE dex_devices SET provision_status = 'Ready for Configuration', updated_at = ? WHERE id = ?", (timestamp, device_id))
            conn.commit()

    def update_device_status(self, device_id, **values):
        allowed = {"provision_status", "last_notify_at", "last_success_at", "last_error", "last_failure_stage", "last_requested_filename", "last_http_status", "last_sip_status", "last_registered_extension", "updated_at"}
        values = {key: value for key, value in values.items() if key in allowed}
        values.setdefault("updated_at", now())
        with self._conn() as conn:
            conn.execute(f"UPDATE dex_devices SET {', '.join(f'{key} = ?' for key in values)} WHERE id = ?", tuple(values.values()) + (device_id,))
            conn.commit()

    def delete_device(self, device_id):
        with self._conn() as conn:
            row = conn.execute("SELECT normalized_mac FROM dex_devices WHERE id = ?", (device_id,)).fetchone()
            if not row:
                raise ValueError("Device not found.")
            conn.execute("DELETE FROM dex_devices WHERE id = ?", (device_id,))
            conn.commit()
            return row["normalized_mac"]

    def create_operation(self, device_id, operation_type, requested_by, **values):
        with self._conn() as conn:
            # A process restart or an unhandled worker termination can leave
            # an operation marked Running forever.  That stale row must not
            # block every later Notify/Reboot attempt for the same phone.
            # Normal DEX operations finish well below five minutes; use the
            # database timestamp so recovery is atomic with the new insert.
            if operation_type in {"notify", "reboot"}:
                stale_before = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
                conn.execute(
                    """UPDATE dex_operations
                       SET status = 'Failed', completed_at = ?,
                           error_stage = 'stale_operation',
                           error_message = 'Previous operation was abandoned and recovered automatically.'
                       WHERE device_id = ? AND operation_type = ?
                         AND status IN ('Pending','Running')
                         AND COALESCE(started_at, created_at) < ?""",
                    (now(), device_id, operation_type, stale_before),
                )
            if operation_type in {"notify", "reboot"} and conn.execute("SELECT 1 FROM dex_operations WHERE device_id = ? AND operation_type = ? AND status IN ('Pending','Running') LIMIT 1", (device_id, operation_type)).fetchone():
                raise ValueError("Operation Already Running")
            cur = conn.execute("""INSERT INTO dex_operations
                (device_id, operation_type, status, requested_by, requested_url,
                 expected_filename, created_at) VALUES (?, ?, 'Pending', ?, ?, ?, ?)""", (device_id, operation_type, requested_by or "", values.get("requested_url", ""), values.get("expected_filename", ""), now()))
            conn.commit()
            return cur.lastrowid

    def update_operation(self, operation_id, **values):
        allowed = {"status", "started_at", "completed_at", "error_stage", "error_message", "sent_at", "sip_response_at", "sip_status", "http_request_at", "http_path", "http_status", "http_bytes", "registration_result"}
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        with self._conn() as conn:
            conn.execute(f"UPDATE dex_operations SET {', '.join(f'{key} = ?' for key in values)} WHERE id = ?", tuple(values.values()) + (operation_id,))
            conn.commit()

    def add_operation_event(self, operation_id, event_type, details=None):
        sanitized = json.dumps(_sanitize_event_details(details or {}), ensure_ascii=True, sort_keys=True)
        with self._conn() as conn:
            conn.execute("INSERT INTO dex_operation_events (operation_id, event_type, event_time, details_json_sanitized) VALUES (?, ?, ?, ?)", (operation_id, event_type, now(), sanitized))
            conn.commit()

    def save_generated_config(self, device_id, filename, sha256, size, archive_path=""):
        with self._conn() as conn:
            conn.execute("UPDATE dex_generated_configs SET active = 0 WHERE device_id = ?", (device_id,))
            existing = conn.execute("SELECT id FROM dex_generated_configs WHERE device_id = ? AND sha256 = ?", (device_id, sha256)).fetchone()
            if existing:
                conn.execute("UPDATE dex_generated_configs SET filename = ?, size = ?, generated_at = ?, published_at = ?, active = 1, archive_path = ? WHERE id = ?", (filename, size, now(), now(), archive_path, existing["id"]))
                generated_id = existing["id"]
            else:
                cur = conn.execute("INSERT INTO dex_generated_configs (device_id, filename, sha256, size, generated_at, published_at, active, archive_path) VALUES (?, ?, ?, ?, ?, ?, 1, ?)", (device_id, filename, sha256, size, now(), now(), archive_path))
                generated_id = cur.lastrowid
            conn.execute("UPDATE dex_devices SET provision_status = 'Config Published', last_requested_filename = ?, updated_at = ? WHERE id = ?", (filename, now(), device_id))
            conn.commit()
            return generated_id

    def discovery_job(self, job_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM dex_discovery_jobs WHERE id = ?", (job_id,)).fetchone()
            return row_dict(row)

    def discovery_results(self, job_id):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT r.*, m.id AS model_id, m.enabled AS model_enabled,
                       m.provisionable AS model_provisionable
                FROM dex_discovery_results r
                LEFT JOIN dex_vendors v ON UPPER(v.vendor_name) = UPPER(r.vendor)
                LEFT JOIN dex_models m ON m.vendor_id = v.id
                    AND lower(m.model_name) = lower(r.model)
                WHERE r.job_id = ?
                  AND UPPER(TRIM(COALESCE(r.vendor, ''))) IN ('FIBERME', 'FANVIL', 'GRANDSTREAM')
                ORDER BY r.id
            """, (job_id,)).fetchall()
            return [dict(row) for row in rows]

    def recent_discovery_jobs(self, limit=10):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM dex_discovery_jobs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(row) for row in rows]

    def recent_operations(self, limit=20):
        with self._conn() as conn:
            rows = conn.execute("""SELECT o.*, d.display_mac, d.detected_model, d.ip_address
                FROM dex_operations o LEFT JOIN dex_devices d ON d.id = o.device_id
                ORDER BY o.id DESC LIMIT ?""", (int(limit),)).fetchall()
            return [dict(row) for row in rows]

    def bulk_set_model_enabled(self, model_ids, enabled):
        ids = sorted({int(value) for value in model_ids})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE dex_models SET enabled = ?, updated_at = ? WHERE id IN ({placeholders})", [int(bool(enabled)), now(), *ids])
            conn.commit()
            return cur.rowcount

    def bulk_delete_models(self, model_ids):
        ids = sorted({int(value) for value in model_ids})
        with self._conn() as conn:
            blocked = []
            detachable = []
            for model_id in ids:
                model = conn.execute("SELECT provisionable, sip_account_count, blf_count FROM dex_models WHERE id = ?", (model_id,)).fetchone()
                if not model:
                    continue
                verified_provisionable = bool(model["provisionable"] and model["sip_account_count"] is not None and model["blf_count"] is not None)
                if verified_provisionable and conn.execute("SELECT 1 FROM dex_devices WHERE model_id = ? LIMIT 1", (model_id,)).fetchone():
                    blocked.append(model_id)
                else:
                    detachable.append(model_id)
            if blocked:
                raise ValueError("Some selected models are assigned to devices and were not deleted: " + ", ".join(map(str, blocked)))
            if detachable:
                placeholders = ",".join("?" for _ in detachable)
                conn.execute(
                    f"UPDATE dex_devices SET model_id = NULL, provision_status = 'Unknown Model', updated_at = ? WHERE model_id IN ({placeholders})",
                    [now(), *detachable],
                )
            deleted = 0
            for model_id in ids:
                cur = conn.execute("DELETE FROM dex_models WHERE id = ?", (model_id,))
                deleted += cur.rowcount
            conn.commit()
        return deleted

    def create_discovery_job(self, cidr, requested_by):
        with self._conn() as conn:
            active = conn.execute("SELECT id FROM dex_discovery_jobs WHERE target_cidr = ? AND status IN ('Pending','Running')", (cidr,)).fetchone()
            if active:
                raise ValueError("A discovery job for this network is already running.")
            cur = conn.execute("INSERT INTO dex_discovery_jobs (target_cidr, requested_by, created_at) VALUES (?, ?, ?)", (cidr, requested_by or "", now()))
            conn.commit()
            return cur.lastrowid

    def claim_discovery_job(self, job_id, owner, lease_seconds=120):
        with self._conn() as conn:
            lease = datetime.now(timezone.utc).timestamp() + lease_seconds
            cur = conn.execute("UPDATE dex_discovery_jobs SET status = 'Running', started_at = COALESCE(started_at, ?), lock_owner = ?, lease_expires_at = ?, current_target = '' WHERE id = ? AND status = 'Pending'", (now(), owner, datetime.fromtimestamp(lease, timezone.utc).isoformat(timespec="seconds"), job_id))
            conn.commit()
            return cur.rowcount == 1

    def update_discovery_job(self, job_id, **values):
        allowed = {"status", "progress", "current_target", "responses_received", "phones_found", "new_devices", "updated_devices", "errors", "error_message", "finished_at", "lease_expires_at"}
        values = {k: v for k, v in values.items() if k in allowed}
        if not values:
            return
        with self._conn() as conn:
            conn.execute(f"UPDATE dex_discovery_jobs SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", tuple(values.values()) + (job_id,))
            conn.commit()

    def cancel_discovery_job(self, job_id):
        with self._conn() as conn:
            cur = conn.execute("""UPDATE dex_discovery_jobs
                SET status = 'Cancelled', finished_at = ?, current_target = ''
                WHERE id = ? AND status IN ('Pending','Running')""", (now(), job_id))
            conn.commit()
            return cur.rowcount == 1

    def add_discovery_result(self, job_id, result):
        with self._conn() as conn:
            conn.execute("INSERT INTO dex_discovery_results (job_id, ip_address, normalized_mac, vendor, model, firmware, raw_user_agent, confidence, response_code, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (job_id, result.get("ip_address", ""), result.get("normalized_mac"), result.get("vendor", ""), result.get("model", ""), result.get("firmware", ""), result.get("raw_user_agent", ""), result.get("confidence", "Unknown"), result.get("response_code"), now()))
            conn.commit()

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from dex import migrations
from dex.discovery import validate_scan_request
from dex.drivers import FanvilDriver, FiberMeDriver, GrandstreamDriver, YealinkDriver
from dex.files import atomic_write_bytes
from dex.jobs import claim_job, enqueue_job
from dex.normalization import normalize_mac
from dex.secrets import DexSecretProvider, SecretConfigurationError
from dex.services import model_delete
from dex.xml_utils import safe_parse_xml


class DexCoreTests(unittest.TestCase):
    def memory_db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        migrations.apply_dex_migrations(conn)
        return conn

    def test_migration_seed_and_idempotency(self):
        conn = self.memory_db()
        migrations.apply_dex_migrations(conn)
        vendors = [row[0] for row in conn.execute("SELECT code FROM dex_vendors ORDER BY code")]
        self.assertEqual(vendors, ["FANVIL", "FIBERME", "GRANDSTREAM", "YEALINK"])
        fiberme = conn.execute("SELECT id FROM dex_vendors WHERE code='FIBERME'").fetchone()[0]
        self.assertEqual({row[0] for row in conn.execute("SELECT model_code FROM dex_models WHERE vendor_id=?", (fiberme,))}, set(migrations.FIBERME_MODELS) | {"FAP2714", "FAP2740G", "FHP702"})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_schema_versions").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models").fetchone()[0], 16 + 3 + len(migrations.USER_SUPPLIED_MODEL_CATALOG))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE vendor_id=?", (fiberme,)).fetchone()[0], 19)
        self.assertTrue(all(row[0] == "Unverified" for row in conn.execute("SELECT verification_status FROM dex_models")))
        conn.close()

    def test_fiberme_capability_catalog_and_new_variants(self):
        conn = self.memory_db()
        expected = {name: (sip, blf_dss) for name, sip, blf_dss in migrations.FIBERME_CAPABILITY_CATALOG}
        rows = conn.execute("SELECT model_name, sip_accounts, blf_keys, dss_keys, capability_note, supplied_spec_text, source_catalog, source_status FROM dex_models WHERE source_catalog=?", (migrations.FIBERME_CAPABILITY_SOURCE,)).fetchall()
        self.assertEqual(len(rows), len(expected))
        self.assertEqual({row[0] for row in rows}, set(expected))
        for row in rows:
            self.assertEqual(row[1], expected[row[0]][0])
            self.assertIsNone(row[2])
            self.assertIsNone(row[3])
            self.assertIn(f"BLF/DSS capacity: {expected[row[0]][1]}", row[4])
            self.assertIn(f"BLF-DSS: {expected[row[0]][1]}", row[5])
            self.assertEqual(row[6:], (migrations.FIBERME_CAPABILITY_SOURCE, migrations.DEX_CATALOG_STATUS))
        for model_name in ("FAP2714", "FAP2740G", "FHP702"):
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE model_name=?", (model_name,)).fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE source_catalog=? AND verification_status='Unverified' AND provisioning_enabled=0", (migrations.FIBERME_CAPABILITY_SOURCE,)).fetchone()[0], len(expected))
        before = conn.execute("SELECT COUNT(*) FROM dex_models").fetchone()[0]
        migrations._seed_fiberme_capability_catalog(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models").fetchone()[0], before)
        conn.close()

    def test_fiberme_capability_seed_preserves_verified_values(self):
        conn = self.memory_db()
        model_id = conn.execute("SELECT id FROM dex_models WHERE model_name='FAP2714P'").fetchone()[0]
        conn.execute("UPDATE dex_models SET verification_status='ProductionVerified', sip_accounts=99, blf_keys=77, dss_keys=88 WHERE id=?", (model_id,))
        conn.commit()
        migrations._seed_fiberme_capability_catalog(conn)
        row = conn.execute("SELECT verification_status, sip_accounts, blf_keys, dss_keys FROM dex_models WHERE id=?", (model_id,)).fetchone()
        self.assertEqual(tuple(row), ("ProductionVerified", 99, 77, 88))
        conn.close()

    def test_user_catalog_is_expanded_and_idempotent(self):
        conn = self.memory_db()
        expected = {(item["vendor"], item["model_code"]) for item in migrations.USER_SUPPLIED_MODEL_CATALOG}
        actual = set(conn.execute("SELECT v.code, m.model_code FROM dex_models m JOIN dex_vendors v ON v.id=m.vendor_id WHERE m.source_catalog=?", (migrations.DEX_CATALOG_SOURCE,)).fetchall())
        self.assertEqual({tuple(row) for row in actual}, expected)
        before = conn.execute("SELECT COUNT(*) FROM dex_models").fetchone()[0]
        migrations._seed_user_supplied_catalog(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models").fetchone()[0], before)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE model_code LIKE '%/%'").fetchone()[0], 0)
        conn.close()

    def test_catalog_preserves_verified_and_non_null_manual_values(self):
        conn = self.memory_db()
        vendor_id = conn.execute("SELECT id FROM dex_vendors WHERE code='YEALINK'").fetchone()[0]
        model_id = conn.execute("SELECT id FROM dex_models WHERE vendor_id=? AND model_code='SIP-T19P-E2'", (vendor_id,)).fetchone()[0]
        conn.execute("UPDATE dex_models SET verification_status='DeviceTested', sip_accounts=99, line_keys=88 WHERE id=?", (model_id,))
        conn.commit()
        migrations._seed_user_supplied_catalog(conn)
        row = conn.execute("SELECT verification_status, sip_accounts, line_keys FROM dex_models WHERE id=?", (model_id,)).fetchone()
        self.assertEqual(tuple(row), ("DeviceTested", 99, 88))

        model_id = conn.execute("SELECT id FROM dex_models WHERE vendor_id=? AND model_code='SIP-T21P-E2'", (vendor_id,)).fetchone()[0]
        conn.execute("UPDATE dex_models SET line_keys=77 WHERE id=?", (model_id,))
        conn.commit()
        migrations._seed_user_supplied_catalog(conn)
        self.assertEqual(conn.execute("SELECT line_keys FROM dex_models WHERE id=?", (model_id,)).fetchone()[0], 77)
        conn.close()

    def test_catalog_categories_and_ambiguous_capacities(self):
        conn = self.memory_db()
        def model(code, vendor):
            return conn.execute("SELECT m.* FROM dex_models m JOIN dex_vendors v ON v.id=m.vendor_id WHERE v.code=? AND m.model_code=?", (vendor, code)).fetchone()
        mp50 = model("MP50", "YEALINK")
        self.assertEqual((mp50["device_category"], mp50["platform_type"], mp50["sip_accounts"], mp50["line_keys"]), ("USBDevice", "USB", None, None))
        native = model("MP54", "YEALINK")
        self.assertEqual((native["device_category"], native["platform_type"], native["sip_accounts"]), ("NativeTeamsZoom", "TeamsZoomNative", None))
        w59 = model("W59R", "YEALINK")
        self.assertIsNone(w59["sip_accounts"])
        self.assertIn("10 SIP", w59["capability_note"])
        dp = model("DP720", "GRANDSTREAM")
        self.assertEqual((dp["device_category"], dp["platform_type"], dp["line_keys"]), ("DECTHandset", "DECT", None))
        self.assertEqual(model("W90B", "YEALINK")["max_handsets"], 250)
        self.assertEqual(model("GDS3705", "GRANDSTREAM")["device_category"], "DoorPhone")
        self.assertEqual(model("PA2", "FANVIL")["device_category"], "PagingAdapter")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE provisioning_enabled=0 AND verification_status='Unverified' AND source_status=? AND source_catalog=?", (migrations.DEX_CATALOG_STATUS, migrations.DEX_CATALOG_SOURCE)).fetchone()[0], len(migrations.USER_SUPPLIED_MODEL_CATALOG))
        conn.close()

    def test_catalog_null_capabilities_are_unknown_not_zero(self):
        conn = self.memory_db()
        row = conn.execute("SELECT sip_accounts, line_keys, simultaneous_calls FROM dex_models WHERE model_code='GDS3705'").fetchone()
        self.assertEqual(tuple(row), (None, None, None))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_models WHERE source_catalog=? AND (sip_accounts=0 OR line_keys=0 OR simultaneous_calls=0)", (migrations.DEX_CATALOG_SOURCE,)).fetchone()[0], 0)
        vendor_id = conn.execute("SELECT id FROM dex_vendors WHERE code='YEALINK'").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO dex_models(vendor_id, model_name, model_code) VALUES (?, 'duplicate', 'sip-t19p-e2')", (vendor_id,))
        conn.close()

    def test_migration_rolls_back_on_failure(self):
        conn = sqlite3.connect(":memory:")
        with mock.patch.object(migrations, "_seed_reference_data", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                migrations.apply_dex_migrations(conn)
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dex_vendors'").fetchone())
        conn.close()

    def test_foreign_keys_are_enforced_and_model_delete_is_restricted(self):
        conn = self.memory_db()
        vendor_id = conn.execute("SELECT id FROM dex_vendors WHERE code='FIBERME'").fetchone()[0]
        model_id = conn.execute("SELECT id FROM dex_models LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO dex_devices(device_name, vendor_id, model_id) VALUES ('phone', ?, ?)", (vendor_id, model_id))
        conn.commit()
        from dex import db as dex_db
        with mock.patch.object(dex_db, "get_connection", return_value=conn):
            ok, message = model_delete(model_id)
        self.assertFalse(ok)
        self.assertIn("referenced", message)
        conn.close()

    def test_mac_normalization_and_duplicate_constraint(self):
        self.assertEqual(normalize_mac("aa:bb-cc.dd:eeff"), "AABBCCDDEEFF")
        conn = self.memory_db()
        conn.execute("INSERT INTO dex_devices(device_name, mac_address) VALUES ('one', 'AABBCCDDEEFF')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO dex_devices(device_name, mac_address) VALUES ('two', 'AABBCCDDEEFF')")
        conn.close()

    def test_conflict_records_can_be_stored_only_as_conflicts(self):
        conn = self.memory_db()
        conn.execute("INSERT INTO dex_devices(device_name, mac_address) VALUES ('one', 'AABBCCDDEEFF')")
        conn.execute("INSERT INTO dex_devices(device_name, mac_address, conflict_status) VALUES ('two', 'AABBCCDDEEFF', 'Conflict')")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_devices WHERE mac_address='AABBCCDDEEFF'").fetchone()[0], 2)
        conn.close()

    def test_secret_provider_requires_external_key_and_round_trips(self):
        with self.assertRaises(SecretConfigurationError):
            DexSecretProvider(environ={}, key_file="/tmp/definitely-missing-dex-key")
        key = Fernet.generate_key().decode("ascii")
        provider = DexSecretProvider(environ={"DEX_ENCRYPTION_KEY": key}, key_file="/tmp/unused")
        encrypted = provider.encrypt("hidden")
        self.assertNotEqual(encrypted, "hidden")
        self.assertEqual(provider.decrypt(encrypted), "hidden")

    def test_discovery_limits_and_public_network_rejection(self):
        with self.assertRaises(ValueError):
            validate_scan_request({"cidr": "8.8.8.0/24"})
        with self.assertRaises(ValueError):
            validate_scan_request({"cidr": "192.168.1.0/24", "max_hosts": 257})
        valid = validate_scan_request({"cidr": "192.168.1.0/24", "max_hosts": 10, "max_concurrency": 2})
        self.assertEqual(valid["max_hosts"], 10)
        from dex.normalization import validate_url
        with self.assertRaises(ValueError):
            validate_url("https://example.com/firmware.bin")

    def test_discovery_individual_ip_and_broadcast_modes(self):
        from dex.discovery import validate_scan_request
        individual = validate_scan_request({
            "cidr": "192.168.99.0/24", "scan_mode": "ip",
            "target_ip": "192.168.99.25", "max_hosts": 256,
        })
        self.assertEqual((individual["scan_mode"], individual["target_ip"], individual["max_hosts"]), ("ip", "192.168.99.25", 1))
        broadcast = validate_scan_request({
            "cidr": "192.168.99.0/24", "scan_mode": "broadcast",
            "target_ip": "192.168.99.255", "max_hosts": 256,
        })
        self.assertEqual((broadcast["scan_mode"], broadcast["target_ip"], broadcast["max_hosts"]), ("broadcast", "192.168.99.255", 256))
        with self.assertRaises(ValueError):
            validate_scan_request({
                "cidr": "192.168.99.0/24", "scan_mode": "broadcast",
                "target_ip": "192.168.99.25",
            })

    def test_safe_xml_and_atomic_publication(self):
        self.assertEqual(safe_parse_xml("<root><item /></root>").tag, "root")
        with self.assertRaises(ValueError):
            safe_parse_xml("<!DOCTYPE root [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><root>&x;</root>")
        with tempfile.TemporaryDirectory() as root:
            path = atomic_write_bytes(root, "AABBCCDDEEFF.cfg", b"safe")
            self.assertEqual(Path(path).read_bytes(), b"safe")
            with self.assertRaises(ValueError):
                atomic_write_bytes(root, "../escape.cfg", b"unsafe")

    def test_audit_masks_secret_summaries(self):
        from dex.audit import record
        from app import app
        conn = self.memory_db()
        with app.test_request_context("/dex/phones"):
            from flask import session
            session["username"] = "tester"
            record(conn, "Secret Test", "Config", "global", before={"password": "do-not-log"}, after={"token": "also-do-not-log"})
        row = conn.execute("SELECT before_summary, after_summary FROM dex_audit_events WHERE action='Secret Test'").fetchone()
        self.assertNotIn("do-not-log", row[0])
        self.assertNotIn("also-do-not-log", row[1])
        conn.close()

    def test_discovery_known_mac_gets_new_ip_without_duplicate(self):
        from dex import discovery
        conn = self.memory_db()
        conn.execute("INSERT INTO dex_discovery_jobs(cidr, max_hosts, max_concurrency, per_host_timeout, total_timeout) VALUES ('192.168.1.0/30', 4, 2, .1, 2)")
        first_job = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with mock.patch.object(discovery, "_arp_map", return_value={"192.168.1.1": "AABBCCDDEEFF"}), mock.patch.object(discovery, "_probe", return_value=(True, {"ports": [80]})):
            discovery.run_scan(first_job, {"cidr": "192.168.1.0/30", "max_hosts": 4, "max_concurrency": 2, "per_host_timeout": .1, "total_timeout": 2}, conn)
        conn.execute("INSERT INTO dex_discovery_jobs(cidr, max_hosts, max_concurrency, per_host_timeout, total_timeout) VALUES ('192.168.1.0/30', 4, 2, .1, 2)")
        second_job = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with mock.patch.object(discovery, "_arp_map", return_value={"192.168.1.2": "AABBCCDDEEFF"}), mock.patch.object(discovery, "_probe", return_value=(True, {"ports": [80]})):
            discovery.run_scan(second_job, {"cidr": "192.168.1.0/30", "max_hosts": 4, "max_concurrency": 2, "per_host_timeout": .1, "total_timeout": 2}, conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_devices WHERE mac_address='AABBCCDDEEFF'").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT ip_address FROM dex_devices WHERE mac_address='AABBCCDDEEFF'").fetchone()[0], "192.168.1.2")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_device_ip_history WHERE device_id=1").fetchone()[0], 2)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM dex_audit_events WHERE action='Device Discovered'").fetchone()[0], 0)
        conn.close()

    def test_exact_ip_discovery_creates_editable_device_without_arp_mac(self):
        from dex import discovery
        conn = self.memory_db()
        conn.execute("INSERT INTO dex_discovery_jobs(cidr, ip_start, ip_end, max_hosts, max_concurrency, per_host_timeout, total_timeout) VALUES ('192.168.99.0/24', '192.168.99.101', '192.168.99.101', 1, 1, .1, 2)")
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with mock.patch.object(discovery, "_arp_map", return_value={}), mock.patch.object(
            discovery, "_probe", return_value=(True, {"ports": [80], "http_attempted": True, "http": []})
        ):
            result = discovery.run_scan(
                job_id,
                {"cidr": "192.168.99.0/24", "scan_mode": "ip", "target_ip": "192.168.99.101", "max_hosts": 1, "max_concurrency": 1, "per_host_timeout": .1, "total_timeout": 2},
                conn,
            )
        self.assertEqual(result["hosts"], 1)
        device = conn.execute("SELECT * FROM dex_devices WHERE ip_address='192.168.99.101'").fetchone()
        self.assertIsNotNone(device)
        self.assertIsNone(device["mac_address"])
        self.assertEqual(device["confidence"], "Unknown")
        self.assertEqual(device["device_status"], "Reachable")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_device_ip_history WHERE device_id=?", (device["id"],)).fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dex_audit_events WHERE action='Device Discovered' AND entity_id=?", (str(device["id"]),)).fetchone()[0], 1)
        conn.close()

    def test_discovery_marks_same_scan_mac_conflict(self):
        from dex import discovery
        conn = self.memory_db()
        conn.execute("INSERT INTO dex_discovery_jobs(cidr, max_hosts, max_concurrency, per_host_timeout, total_timeout) VALUES ('192.168.1.0/30', 4, 2, .1, 2)")
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with mock.patch.object(discovery, "_arp_map", return_value={"192.168.1.1": "AABBCCDDEEFF", "192.168.1.2": "AABBCCDDEEFF"}), mock.patch.object(discovery, "_probe", return_value=(True, {})):
            discovery.run_scan(job_id, {"cidr": "192.168.1.0/30", "max_hosts": 4, "max_concurrency": 2, "per_host_timeout": .1, "total_timeout": 2}, conn)
        self.assertEqual(conn.execute("SELECT conflict_status FROM dex_devices WHERE mac_address='AABBCCDDEEFF'").fetchone()[0], "Conflict")
        conn.close()

    def test_device_deletion_does_not_delete_pbx_extension(self):
        from dex.services import device_delete
        fd, path = tempfile.mkstemp(prefix="dex-device-", suffix=".db")
        os.close(fd)
        from dex import db as dex_db
        def get_test_db():
            conn = sqlite3.connect(path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        try:
            conn = get_test_db()
            migrations.apply_dex_migrations(conn)
            conn.execute("CREATE TABLE extensions(ext TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO extensions(ext) VALUES ('1001')")
            conn.execute("INSERT INTO dex_devices(device_name, mac_address) VALUES ('phone', 'AABBCCDDEEFF')")
            device_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            conn.close()
            with mock.patch.object(dex_db, "get_connection", side_effect=get_test_db):
                ok, message = device_delete(device_id)
            self.assertTrue(ok, message)
            conn = get_test_db()
            self.assertIsNotNone(conn.execute("SELECT 1 FROM extensions WHERE ext='1001'").fetchone())
            self.assertIsNone(conn.execute("SELECT 1 FROM dex_devices WHERE id=?", (device_id,)).fetchone())
            conn.close()
        finally:
            os.unlink(path)

    def test_job_idempotency_and_database_lease_claim(self):
        fd, path = tempfile.mkstemp(prefix="dex-job-", suffix=".db")
        os.close(fd)
        original_get_db = __import__("db").get_db
        from dex import db as dex_db
        def get_test_db():
            conn = sqlite3.connect(path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        try:
            conn = get_test_db()
            migrations.apply_dex_migrations(conn)
            conn.commit()
            conn.close()
            with mock.patch.object(dex_db, "get_connection", side_effect=get_test_db):
                first, created = enqueue_job("unit", {}, "tester", "same-key")
                second, created_again = enqueue_job("unit", {}, "tester", "same-key")
                self.assertTrue(created)
                self.assertFalse(created_again)
                claimed = claim_job("worker-a")
                self.assertEqual(claimed["id"], first["id"])
                self.assertIsNone(claim_job("worker-b"))
        finally:
            os.unlink(path)

    def test_each_vendor_driver_is_independent_and_unsupported(self):
        drivers = [FiberMeDriver(), FanvilDriver(), GrandstreamDriver(), YealinkDriver()]
        self.assertEqual({driver.vendor_code for driver in drivers}, {"FIBERME", "FANVIL", "GRANDSTREAM", "YEALINK"})
        for driver in drivers:
            result = driver.request_reboot({})
            self.assertIn(result.status, {"Unsupported", "PendingDocumentation"})
            self.assertNotEqual(result.status, "Supported")
        fiberme_source = Path("dex/drivers/fiberme.py").read_text()
        self.assertNotIn("from .fanvil", fiberme_source)
        self.assertNotIn("FanvilDriver", fiberme_source)

    def test_dex_code_has_no_shell_true(self):
        for path in Path("dex").rglob("*.py"):
            self.assertNotIn("shell=True", path.read_text(), str(path))

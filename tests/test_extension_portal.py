import os
import re
import shutil
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

import app
import db


class ExtensionPortalTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db_path = db.DB_PATH

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rcm_extension_portal_test_")
        self.test_db = os.path.join(self.temp_dir, "rcm.db")
        shutil.copy2(self.original_db_path, self.test_db)
        db.DB_PATH = self.test_db
        db.init_db()
        app.app.config["TESTING"] = True
        self.recording_dir = os.path.join(self.temp_dir, "recordings")
        os.makedirs(self.recording_dir)
        self.original_recording_dir = app.EXTENSION_PORTAL_RECORDING_DIR
        app.EXTENSION_PORTAL_RECORDING_DIR = self.recording_dir
        self.patchers = [
            patch.object(db, "sync_cdr_records", lambda: None),
            patch.object(app, "audit_event", lambda *args, **kwargs: None),
            patch.object(app, "add_pending_change", lambda *args, **kwargs: None),
            patch.object(app, "run_asterisk_sync", lambda *args, **kwargs: True),
            patch.object(app, "run_asterisk_cli", lambda *args, **kwargs: True),
            patch.object(app.asterisk_helper, "get_available_moh_classes", lambda: ["default"]),
            patch.object(app.asterisk_helper, "get_pjsip_contacts", lambda: {}),
            patch.object(app.asterisk_helper, "get_pjsip_endpoint_states", lambda: {}),
            patch.object(app.asterisk_helper, "get_asterisk_db_features", lambda: {}),
            patch.object(app.asterisk_helper, "write_extension_configs", lambda *args, **kwargs: True),
            patch.object(app.asterisk_helper, "apply_extension_features", lambda *args, **kwargs: True),
            patch.object(app.asterisk_helper, "apply_extension_runtime_flags", lambda *args, **kwargs: True),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = app.app.test_client()
        self.security_headers = {"X-Enforce-Security": "1"}

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        app.EXTENSION_PORTAL_RECORDING_DIR = self.original_recording_dir
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir)

    def login_extension(self, ext="2121", password="PortalQa9"):
        success, message = db.update_extension_web_password(ext, password)
        self.assertTrue(success, message)
        return self.client.post("/", data={"username": ext, "password": password}, headers=self.security_headers)

    def test_migration_creates_exactly_one_secure_user_per_extension(self):
        extensions = db.get_all_extensions()
        users = [db.get_extension_web_user(item["ext"]) for item in extensions]
        self.assertTrue(all(users))
        self.assertEqual(len(users), len({user["id"] for user in users}))
        self.assertTrue(all(user["username"] == user["extension_ext"] for user in users))
        self.assertTrue(all(user["password"].startswith(("scrypt:", "pbkdf2:")) for user in users))
        before = db.get_extension_web_user("2121")["password"]
        db.ensure_extension_web_users()
        self.assertEqual(before, db.get_extension_web_user("2121")["password"])

    def test_extension_login_uses_web_password_and_is_isolated(self):
        # Make this assertion independent of whatever password happens to be
        # present in the copied fixture database.
        success, message = db.update_extension_web_password("2121", "PortalRegressionQa9")
        self.assertTrue(success, message)
        sip_password = db.get_extension("2121")["secret"]
        self.assertFalse(db.authenticate_user("2121", sip_password))
        response = self.login_extension()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/portal/dashboard", response.location)
        for path in ("/portal/dashboard", "/portal/my-extension", "/portal/calls", "/portal/recordings", "/portal/profile"):
            self.assertEqual(self.client.get(path, headers=self.security_headers).status_code, 200)
        for path in ("/dashboard", "/extensions", "/users", "/privileges", "/cdr", "/call-records"):
            response = self.client.get(path, headers=self.security_headers)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("PBX Settings", response.get_data(as_text=True))

    def test_calls_and_export_are_filtered_by_session_extension(self):
        connection = db.get_db()
        for uniqueid, src, dst, caller_id in (
            ("portal-owned-out", "2121", "QAOUT", "Portal QA"),
            ("portal-owned-in", "QAIN", "2121", "Portal QA"),
            ("portal-unrelated", "QAOTHER", "4321", "Portal QA"),
        ):
            connection.execute(
                "INSERT OR REPLACE INTO cdr_records (uniqueid, src, dst, clid, start_time, duration, billsec, status) VALUES (?, ?, ?, ?, ?, 20, 10, 'ANSWERED')",
                (uniqueid, src, dst, caller_id, "2026-07-20 10:00:00"),
            )
        connection.commit()
        connection.close()
        self.login_extension()
        body = self.client.get("/portal/calls?q=Portal+QA", headers=self.security_headers).get_data(as_text=True)
        self.assertIn("QAOUT", body)
        self.assertIn("QAIN", body)
        self.assertNotIn("QAOTHER", body)
        exported = self.client.get("/portal/calls/export?q=Portal+QA", headers=self.security_headers).get_data(as_text=True)
        self.assertIn("QAOUT", exported)
        self.assertIn("QAIN", exported)
        self.assertNotIn("QAOTHER", exported)

    def test_calls_and_recordings_support_all_page_sizes(self):
        self.login_extension()
        expected_sizes = (10, 20, 30, 50, 70, 100)
        calls = self.client.get("/portal/cdr?per_page=70", headers=self.security_headers)
        self.assertEqual(calls.status_code, 200)
        calls_body = calls.get_data(as_text=True)
        self.assertIn('value="70" selected', calls_body)
        recordings = self.client.get("/portal/recordings?per_page=30", headers=self.security_headers)
        self.assertEqual(recordings.status_code, 200)
        recordings_body = recordings.get_data(as_text=True)
        self.assertIn('value="30" selected', recordings_body)
        for size in expected_sizes:
            self.assertIn(f'value="{size}"', calls_body)
            self.assertIn(f'value="{size}"', recordings_body)

    def test_recording_play_and_download_enforce_ownership(self):
        for filename in ("2121-3001-owned.wav", "3001-4321-other.wav"):
            with wave.open(os.path.join(self.recording_dir, filename), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(struct.pack("<h", 0) * 800)
        self.login_extension()
        playback = self.client.get("/portal/recordings/file/2121-3001-owned.wav", headers=self.security_headers)
        self.assertEqual(playback.status_code, 200)
        playback.close()
        download = self.client.get("/portal/recordings/file/2121-3001-owned.wav?download=1", headers=self.security_headers)
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))
        download.close()
        self.assertEqual(self.client.get("/portal/recordings/file/3001-4321-other.wav", headers=self.security_headers).status_code, 403)

    def test_dashboard_handles_recording_names_with_timestamp_parts(self):
        filename = "2121-5001-20260720-113000.wav"
        with wave.open(os.path.join(self.recording_dir, filename), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(struct.pack("<h", 0) * 800)

        self.login_extension()
        response = self.client.get("/portal/dashboard", headers=self.security_headers)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("5001", body)

    def test_sip_and_web_password_changes_are_independent(self):
        self.login_extension()
        web_hash = db.get_extension_web_user("2121")["password"]
        response = self.client.post("/portal/my-extension", data={
            "ext": "3001", "name": "Portal User", "email": "portal@example.com",
            "mobile": "0100000000", "sip_password": "NewSipQa9", "vm_password": "4567",
            "ring_time": "45", "dnd": "on", "fwd_always": "3001",
            "fwd_noanswer": "", "fwd_busy": "",
        }, headers=self.security_headers)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_extension("2121")["secret"], "NewSipQa9")
        self.assertNotEqual(db.get_extension("3001")["name"], "Portal User")
        self.assertEqual(db.get_extension_web_user("2121")["password"], web_hash)
        response = self.client.post("/portal/profile", data={
            "current_password": "PortalQa9", "new_password": "ChangedQa8", "confirm_password": "ChangedQa8"
        }, headers=self.security_headers)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db.authenticate_user("2121", "ChangedQa8"))
        self.assertFalse(db.authenticate_user("2121", "PortalQa9"))
        self.assertEqual(db.get_extension("2121")["secret"], "NewSipQa9")

    def test_extension_create_and_delete_include_web_user_transactionally(self):
        data = {
            "ext": "6198", "enabled": 1, "name": "Portal QA", "callerid_number": "6198",
            "secret": "SipQa123", "max_contacts": 3, "max_expiration": 120, "ring_time": 60,
            "vm_enabled": 0, "vm_password": "1234", "record_mode": "noo", "dtmf_mode": "rfc4733",
            "moh_class": "default", "video_support": 0, "direct_media": 0, "nat": 0,
            "codecs": "alaw,ulaw", "followme": [], "mobile": "", "email": "", "allow_spy": 1,
        }
        self.assertTrue(db.add_extension(data))
        password = data["_web_password_once"]
        self.assertRegex(password, r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d]{8}$")
        self.assertTrue(db.authenticate_user("6198", password))
        deleted, message = db.delete_extension("6198")
        self.assertTrue(deleted, message)
        self.assertIsNone(db.get_extension("6198"))
        self.assertIsNone(db.get_extension_web_user("6198"))

    def test_admin_creation_displays_generated_password_only_in_response(self):
        login = self.client.post("/", data={"username": "admin", "password": "admin123"}, headers=self.security_headers)
        self.assertEqual(login.status_code, 302)
        response = self.client.post("/extensions/add", data={
            "ext": "6197", "enabled": "on", "name": "Portal QA", "callerid_number": "6197",
            "secret": "SipAdmin9", "max_contacts": "3", "max_expiration": "120", "ring_time": "60",
            "vm_password": "1234", "record_mode": "noo", "dtmf_mode": "rfc4733",
            "moh_class": "default", "codecs[]": ["alaw", "ulaw"], "allow_spy": "on",
            "email": "portal6197@example.com", "web_password": "",
        }, headers=self.security_headers)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        match = re.search(r'id="createdWebPassword"[^>]*>([^<]+)</code>', body)
        self.assertIsNotNone(match)
        password = match.group(1).strip()
        self.assertTrue(db.authenticate_user("6197", password))
        self.assertNotIn(password, db.get_extension_web_user("6197")["password"])
        self.assertNotIn(password, response.headers.get("Set-Cookie", ""))
        self.assertNotIn(password, self.client.get("/extensions", headers=self.security_headers).get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

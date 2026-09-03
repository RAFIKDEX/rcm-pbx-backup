import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock
from werkzeug.datastructures import MultiDict

import db
import rcm_queue_db
import asterisk_helper


class PbxSettingsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.old_main_db = db.DB_PATH
        cls.old_queue_db = rcm_queue_db.DB_PATH
        cls.old_pbx_settings_file = db.PBX_SETTINGS_FILE
        cls.old_pbx_operation_log_file = db.PBX_OPERATION_LOG_FILE
        db.DB_PATH = os.path.join(cls.tmpdir.name, "main.db")
        db.PBX_SETTINGS_FILE = os.path.join(cls.tmpdir.name, "pbx_settings.json")
        db.PBX_OPERATION_LOG_FILE = os.path.join(cls.tmpdir.name, "pbx_operation_log.json")
        rcm_queue_db.DB_PATH = os.path.join(cls.tmpdir.name, "queue.db")
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.flask_app = cls.app_module.app
        cls.flask_app.config.update(TESTING=True, SECRET_KEY="testsecret")

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.old_main_db
        db.PBX_SETTINGS_FILE = cls.old_pbx_settings_file
        db.PBX_OPERATION_LOG_FILE = cls.old_pbx_operation_log_file
        rcm_queue_db.DB_PATH = cls.old_queue_db
        cls.tmpdir.cleanup()

    def setUp(self):
        db.init_db()
        rcm_queue_db.init_queue_db()
        self.client = self.flask_app.test_client()

    def login(self, role="admin"):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = role
            sess["role"] = role

    def write_runtime_files(self, tmpdir):
        pjsip = os.path.join(tmpdir, "pjsip.conf")
        rtp = os.path.join(tmpdir, "rtp.conf")
        features = os.path.join(tmpdir, "features.conf")
        asterisk_conf = os.path.join(tmpdir, "asterisk.conf")
        with open(pjsip, "w", encoding="utf-8") as f:
            f.write("""[global]
type=global
endpoint_identifier_order=username,auth_username,ip

[transport-udp-main]
type=transport
protocol=udp
bind=0.0.0.0:5060

[transport-tcp-main]
type=transport
protocol=tcp
bind=0.0.0.0:5080

[transport-tls-main]
type=transport
protocol=tls
bind=0.0.0.0:5061
cert_file=/etc/asterisk/keys/asterisk.crt
""")
        with open(rtp, "w", encoding="utf-8") as f:
            f.write("[general]\nrtpstart=10000\nrtpend=20000\nstrictrtp=yes\n")
        with open(features, "w", encoding="utf-8") as f:
            f.write("[general]\natxferabort=*0\n\n[featuremap]\nblindxfer=>#1\n")
        with open(asterisk_conf, "w", encoding="utf-8") as f:
            f.write("[options]\nmaxcalls=75\n")
        return pjsip, rtp, features, asterisk_conf

    def test_runtime_settings_are_loaded_from_asterisk_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pjsip, rtp, features, asterisk_conf = self.write_runtime_files(tmpdir)
            with mock.patch.object(asterisk_helper, "PJSIP_FILE", pjsip), \
                 mock.patch.object(asterisk_helper, "RTP_FILE", rtp), \
                 mock.patch.object(asterisk_helper, "FEATURES_FILE", features), \
                 mock.patch.object(asterisk_helper, "ASTERISK_CONF_FILE", asterisk_conf), \
                 mock.patch("asterisk_helper.run_asterisk_cmd", return_value="username\nauth_username\nip\nheader\nanonymous\n"):
                settings = asterisk_helper.read_pbx_runtime_settings()
        self.assertEqual(settings["sip"]["transports"]["udp"]["port"], 5060)
        self.assertEqual(settings["sip"]["transports"]["tcp"]["port"], 5080)
        self.assertEqual(settings["sip"]["transports"]["tls"]["port"], 5061)
        self.assertEqual(settings["rtp"]["start"], 10000)
        self.assertEqual(settings["rtp"]["end"], 20000)
        self.assertEqual(settings["global"]["max_concurrent_calls"], 75)
        self.assertEqual(settings["sip"]["endpoint_identifier_order"], ["username", "auth_username", "ip"])

    def test_core_runtime_limits_are_parsed_from_asterisk_cli(self):
        output = """
PBX Core settings
-----------------
  Maximum calls:               100
  Maximum load average:        4.500000
"""
        with mock.patch("asterisk_helper.run_asterisk_cmd", return_value=output):
            limits = asterisk_helper.get_pbx_core_runtime_limits()
        self.assertTrue(limits["raw_available"])
        self.assertEqual(limits["max_concurrent_calls"], 100)
        self.assertEqual(limits["maxload"], 4.5)

        with mock.patch("asterisk_helper.run_asterisk_cmd", return_value="  Maximum calls:               Not set\n"):
            limits = asterisk_helper.get_pbx_core_runtime_limits()
        self.assertEqual(limits["max_concurrent_calls"], 0)

    def test_apply_preserves_tls_and_unrelated_rtp_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pjsip, rtp, features, asterisk_conf = self.write_runtime_files(tmpdir)
            payload = {
                "max_concurrent_calls": 150,
                "sip_ports": {"udp": 5062, "tcp": 5082, "tls": 5063},
                "rtp_start": 12000,
                "rtp_end": 22000,
                "user_agent": "RCM-Test",
                "endpoint_identifier_order": ["ip", "username"],
                "blind_transfer_timeout": 20,
            }
            with mock.patch.object(asterisk_helper, "PJSIP_FILE", pjsip), \
                 mock.patch.object(asterisk_helper, "RTP_FILE", rtp), \
                 mock.patch.object(asterisk_helper, "FEATURES_FILE", features), \
                 mock.patch.object(asterisk_helper, "ASTERISK_CONF_FILE", asterisk_conf), \
                 mock.patch("asterisk_helper.run_asterisk_cmd", return_value="Reloaded"):
                ok, msg = asterisk_helper.apply_pbx_runtime_settings(payload)
            self.assertTrue(ok, msg)
            with open(pjsip, "r", encoding="utf-8") as f:
                pjsip_text = f.read()
            with open(rtp, "r", encoding="utf-8") as f:
                rtp_text = f.read()
            with open(features, "r", encoding="utf-8") as f:
                features_text = f.read()
            with open(asterisk_conf, "r", encoding="utf-8") as f:
                asterisk_text = f.read()
        self.assertIn("[transport-tls-main]", pjsip_text)
        self.assertIn("cert_file=/etc/asterisk/keys/asterisk.crt", pjsip_text)
        self.assertIn("bind=0.0.0.0:5063", pjsip_text)
        self.assertIn("user_agent=RCM-Test", pjsip_text)
        self.assertIn("endpoint_identifier_order=ip,username", pjsip_text)
        self.assertIn("rtpstart=12000", rtp_text)
        self.assertIn("rtpend=22000", rtp_text)
        self.assertIn("strictrtp=yes", rtp_text)
        self.assertIn("transferdigittimeout=20", features_text)
        self.assertIn("maxcalls=150", asterisk_text)

    def test_invalid_pbx_settings_are_rejected(self):
        with mock.patch("asterisk_helper.get_supported_endpoint_identifiers", return_value=["username", "ip"]), \
             mock.patch("asterisk_helper.get_available_moh_classes", return_value=["default"]):
            parsed, submitted, errors = self.app_module.validate_pbx_settings_form(MultiDict({
                "udp_port": "",
                "max_concurrent_calls": "0",
                "tcp_port": "5060",
                "tls_port": "5060",
                "rtp_start": "20000",
                "rtp_end": "10000",
                "user_agent": "bad\nagent",
                "dtmf_mode": "bad",
                "moh_class": "missing",
                "ring_time": "999",
                "blind_transfer_timeout": "0",
            }))
        self.assertGreaterEqual(len(errors), 5)
        self.assertIn("UDP Port is required.", errors)

    def test_stun_unsafe_config_text_is_rejected(self):
        with mock.patch("asterisk_helper.get_supported_endpoint_identifiers", return_value=["username", "ip"]), \
             mock.patch("asterisk_helper.get_available_moh_classes", return_value=["default"]):
            parsed, submitted, errors = self.app_module.validate_pbx_settings_form(MultiDict({
                "max_concurrent_calls": "100",
                "udp_port": "5060",
                "tcp_port": "5061",
                "tls_port": "5062",
                "rtp_start": "10000",
                "rtp_end": "20000",
                "user_agent": "RCM",
                "endpoint_identifier_order": ["username", "ip"],
                "dtmf_mode": "rfc4733",
                "moh_class": "default",
                "ring_time": "60",
                "blind_transfer_timeout": "15",
                "keep_alive_interval": "90",
                "max_forwards": "70",
                "featuredigittimeout": "1000",
                "atxfernoanswertimeout": "15",
                "maxload": "0",
                "stunaddr": "bad;value",
            }))
        self.assertIn("STUN Server Address contains characters that are unsafe for Asterisk configuration.", errors)

    def test_non_admin_cannot_access_pbx_settings(self):
        self.login("agent")
        response = self.client.get("/pbx-settings")
        self.assertEqual(response.status_code, 302)

    def test_pbx_operation_log_requires_admin(self):
        self.login("agent")
        response = self.client.get("/pbx-settings/operation-log")
        self.assertEqual(response.status_code, 302)

    def test_pbx_operation_log_records_setting_diffs(self):
        before = {
            "extension_defaults": {"dtmf_mode": "rfc4733"},
            "global_settings": {"max_concurrent_calls": 100}
        }
        after = {
            "extension_defaults": {"dtmf_mode": "info"},
            "global_settings": {"max_concurrent_calls": 100}
        }
        self.assertTrue(db.log_pbx_settings_change(before, after, "admin", "127.0.0.1"))
        logs = db.get_pbx_operation_logs()
        self.assertEqual(logs[0]["username"], "admin")
        self.assertEqual(logs[0]["changes"][0]["setting"], "extension_defaults.dtmf_mode")
        self.assertEqual(logs[0]["changes"][0]["old"], "rfc4733")
        self.assertEqual(logs[0]["changes"][0]["new"], "info")

    def test_admin_can_view_pbx_operation_log(self):
        self.login("admin")
        response = self.client.get("/pbx-settings/operation-log")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Operation Log", response.data)

    def test_new_extension_uses_saved_dtmf_default_and_can_override(self):
        db.save_pbx_settings({"extension_defaults": {"dtmf_mode": "info", "blind_transfer_timeout": 15}})
        data = {
            "ext": "2222",
            "enabled": 1,
            "name": "Default DTMF",
            "callerid_number": "2222",
            "secret": "pass",
            "max_contacts": 3,
            "max_expiration": 120,
            "ring_time": 60,
            "vm_enabled": 0,
            "vm_password": "1234",
            "record_mode": "noo",
            "dtmf_mode": db.get_pbx_settings()["extension_defaults"]["dtmf_mode"],
            "direct_media": 0,
            "nat": 0,
            "codecs": "alaw,ulaw",
            "followme": [],
            "mobile": "",
            "email": "",
            "allow_spy": 1,
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(asterisk_helper, "EP_FILE", os.path.join(tmpdir, "endpoint.conf")), \
             mock.patch.object(asterisk_helper, "AUTH_FILE", os.path.join(tmpdir, "auth.conf")), \
             mock.patch.object(asterisk_helper, "AOR_FILE", os.path.join(tmpdir, "aor.conf")), \
             mock.patch.object(asterisk_helper, "DP_FILE", os.path.join(tmpdir, "extensions_gui.conf")), \
             mock.patch.object(asterisk_helper, "CTX_FILE", os.path.join(tmpdir, "context_exten.conf")), \
             mock.patch.object(asterisk_helper, "VM_FILE", os.path.join(tmpdir, "voicemail.conf")), \
             mock.patch.object(asterisk_helper, "FM_FILE", os.path.join(tmpdir, "followme.conf")), \
             mock.patch("db.get_outbound_routes", return_value=[]):
            asterisk_helper.write_extension_configs(data, reload=False)
            with open(os.path.join(tmpdir, "endpoint.conf"), "r", encoding="utf-8") as f:
                default_content = f.read()
            data["dtmf_mode"] = "inband"
            data["ext"] = "2223"
            data["callerid_number"] = "2223"
            asterisk_helper.write_extension_configs(data, reload=False)
            with open(os.path.join(tmpdir, "endpoint.conf"), "r", encoding="utf-8") as f:
                override_content = f.read()
        self.assertIn("dtmf_mode=info", default_content)
        self.assertIn("dtmf_mode=inband", override_content)


if __name__ == "__main__":
    unittest.main()

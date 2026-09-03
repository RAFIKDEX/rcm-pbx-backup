import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock
import json
import wave
from werkzeug.datastructures import MultiDict

import db
import rcm_queue_db


class IvrValidationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.old_main_db = db.DB_PATH
        cls.old_queue_db = rcm_queue_db.DB_PATH
        cls.old_ivr_file = db.IVR_FILE
        cls.old_mc_file = db.MC_FILE
        
        # Override paths to avoid modifying the real DBs
        db.DB_PATH = os.path.join(cls.tmpdir.name, "main.db")
        rcm_queue_db.DB_PATH = os.path.join(cls.tmpdir.name, "queue.db")
        db.IVR_FILE = os.path.join(cls.tmpdir.name, "rcm_ivr.json")
        db.MC_FILE = os.path.join(cls.tmpdir.name, "rcm_media_center.json")
        
        # Reload app module with new db paths
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.flask_app = cls.app_module.app
        cls.flask_app.config.update(TESTING=True, SECRET_KEY="testsecret")

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.old_main_db
        rcm_queue_db.DB_PATH = cls.old_queue_db
        db.IVR_FILE = cls.old_ivr_file
        db.MC_FILE = cls.old_mc_file
        cls.tmpdir.cleanup()

    def setUp(self):
        # Reset IVR JSON file content
        db.save_ivrs([])
        prompt_path = os.path.join(self.tmpdir.name, "welcome_prompt.wav")
        with wave.open(prompt_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 8000)
        db.save_media_center_db({
            "prompts": [{
                "id": "welcome_prompt",
                "name": "welcome_prompt",
                "type": "ivr",
                "path": prompt_path,
                "created_at": "2026-07-13T00:00:00"
            }],
            "moh_classes": []
        })
        self.client = self.flask_app.test_client()

    def login_client(self, username="admin", role="admin"):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = username
            sess['role'] = role

    def test_database_level_validation_raises_value_error_on_duplicates(self):
        duplicate_ivrs = [
            {
                "num": "7000",
                "name": "test_ivr",
                "prompt_id": "1",
                "mappings": [
                    {"key": "1", "dest": "5001", "dest_type": "extension"},
                    {"key": "1", "dest": "5002", "dest_type": "extension"}
                ]
            }
        ]
        with self.assertRaises(ValueError) as context:
            db.save_ivrs(duplicate_ivrs)
        self.assertIn("Duplicate DTMF options are not allowed", str(context.exception))

    def test_add_ivr_with_duplicate_dtmf_is_rejected_with_400(self):
        self.login_client()
        post_data = MultiDict([
            ("num", "7001"),
            ("name", "main_menu"),
            ("prompt_id", "welcome_prompt"),
            ("timeout", "10"),
            ("digit_timeout", "4"),
            ("loops", "3"),
            ("fail_mode", "hangup"),
            ("fail_ext", ""),
            ("mapping_keys[]", "1"),
            ("mapping_keys[]", "1"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dests[]", "5001"),
            ("mapping_dests[]", "5002")
        ])
        response = self.client.post("/ivr/add", data=post_data)
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Duplicate DTMF keys", data["msg"])
        
        # Verify nothing was saved
        ivrs = db.get_ivrs()
        self.assertEqual(len(ivrs), 0)

    def test_add_ivr_with_unique_dtmf_is_accepted(self):
        self.login_client()
        post_data = MultiDict([
            ("num", "7002"),
            ("name", "sales_menu"),
            ("prompt_id", "welcome_prompt"),
            ("timeout", "10"),
            ("digit_timeout", "4"),
            ("loops", "3"),
            ("fail_mode", "hangup"),
            ("fail_ext", ""),
            ("mapping_keys[]", "1"),
            ("mapping_keys[]", "2"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dests[]", "5001"),
            ("mapping_dests[]", "5002")
        ])
        # Mock asterisk sync to avoid subprocess/system errors
        with mock.patch("asterisk_helper.sync_ivr_dialplan") as mock_sync:
            response = self.client.post("/ivr/add", data=post_data)
            self.assertEqual(response.status_code, 302)  # Successful redirect
            
        ivrs = db.get_ivrs()
        self.assertEqual(len(ivrs), 1)
        self.assertEqual(ivrs[0]["num"], "7002")
        self.assertEqual(len(ivrs[0]["mappings"]), 2)

    def test_add_ivr_saves_advanced_options_and_ultra_number(self):
        self.login_client()
        post_data = MultiDict([
            ("num", "7005"),
            ("name", "advanced_menu"),
            ("prompt_id", "welcome_prompt"),
            ("timeout", "10"),
            ("digit_timeout", "4"),
            ("loops", "3"),
            ("fail_mode", "hangup"),
            ("fail_ext", ""),
            ("dial_extension", "on"),
            ("replace_display_name", "on"),
            ("auto_record", "on"),
            ("mapping_keys[]", "1"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dests[]", "5001"),
            ("ultra_numbers[]", "1234"),
            ("ultra_dest_types[]", "queue"),
            ("ultra_dests[]", "6500")
        ])
        with mock.patch("asterisk_helper.sync_ivr_dialplan"):
            response = self.client.post("/ivr/add", data=post_data)
            self.assertEqual(response.status_code, 302)

        ivrs = db.get_ivrs()
        self.assertEqual(len(ivrs), 1)
        self.assertTrue(ivrs[0]["dial_extension"])
        self.assertTrue(ivrs[0]["replace_display_name"])
        self.assertTrue(ivrs[0]["auto_record"])
        self.assertEqual(ivrs[0]["digit_timeout"], 4)
        self.assertEqual(ivrs[0]["ultra_numbers"][0]["number"], "1234")
        self.assertEqual(ivrs[0]["ultra_numbers"][0]["dest"], "6500")

    def test_add_ivr_accepts_general_prompt(self):
        self.login_client()
        prompt_path = os.path.join(self.tmpdir.name, "general_prompt.wav")
        with wave.open(prompt_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 8000)
        db.save_media_center_db({
            "prompts": [{
                "id": "general_prompt",
                "name": "general_prompt",
                "type": "general",
                "path": prompt_path,
                "created_at": "2026-07-13T00:00:00"
            }],
            "moh_classes": []
        })
        post_data = MultiDict([
            ("num", "7004"),
            ("name", "general_menu"),
            ("prompt_id", "general_prompt"),
            ("timeout", "10"),
            ("loops", "3"),
            ("fail_mode", "hangup"),
            ("fail_ext", ""),
            ("mapping_keys[]", "1"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dests[]", "5001")
        ])
        with mock.patch("asterisk_helper.sync_ivr_dialplan"):
            response = self.client.post("/ivr/add", data=post_data)
            self.assertEqual(response.status_code, 302)

        ivrs = db.get_ivrs()
        self.assertEqual(len(ivrs), 1)
        self.assertEqual(ivrs[0]["prompt_id"], "general_prompt")

    def test_system_prompt_does_not_include_or_accept_general_prompt(self):
        self.login_client()
        prompt_path = os.path.join(self.tmpdir.name, "general_prompt.wav")
        with wave.open(prompt_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 8000)
        db.save_media_center_db({
            "prompts": [{
                "id": "general_prompt",
                "name": "general_prompt",
                "type": "general",
                "path": prompt_path,
                "created_at": "2026-07-13T00:00:00"
            }],
            "moh_classes": []
        })

        system_prompts = self.app_module.get_system_prompts()
        self.assertTrue(system_prompts)
        self.assertTrue(all(prompt["type"] == "system" for prompt in system_prompts))
        self.assertNotIn("general_prompt", {prompt["id"] for prompt in system_prompts})
        ok, msg = self.app_module.validate_prompt_type("general_prompt", "system")
        self.assertFalse(ok)
        self.assertIn("System Prompt", msg)

    def test_prompt_rename_cannot_cross_custom_system_libraries(self):
        self.login_client()
        custom_path = os.path.join(self.tmpdir.name, "custom.wav")
        system_path = os.path.join(self.tmpdir.name, "system.wav")
        for path in (custom_path, system_path):
            with wave.open(path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(b"\x00\x00" * 8000)
        db.save_media_center_db({
            "prompts": [
                {"id": "custom_prompt", "name": "custom_prompt", "type": "ivr", "path": custom_path},
                {"id": "system_prompt", "name": "system_prompt", "type": "system", "path": system_path},
            ],
            "moh_classes": []
        })

        response = self.client.post("/media/prompt/rename", data={
            "id": "custom_prompt",
            "new_name": "custom_prompt",
            "type": "system"
        })
        self.assertEqual(response.status_code, 302)
        prompts = {p["id"]: p for p in db.get_media_center_db()["prompts"]}
        self.assertEqual(prompts["custom_prompt"]["type"], "ivr")

        response = self.client.post("/media/prompt/rename", data={
            "id": "system_prompt",
            "new_name": "system_prompt",
            "type": "ivr"
        })
        self.assertEqual(response.status_code, 302)
        prompts = {p["id"]: p for p in db.get_media_center_db()["prompts"]}
        self.assertEqual(prompts["system_prompt"]["type"], "system")

    def test_edit_ivr_with_duplicate_dtmf_is_rejected_with_400(self):
        self.login_client()
        # Create an initial valid IVR first
        initial_ivr = {
            "num": "7003",
            "name": "billing_menu",
            "prompt_id": "prompt_billing",
            "timeout": 10,
            "loops": 3,
            "fail_mode": "hangup",
            "fail_ext": "",
            "mappings": [{"key": "1", "dest": "5001", "dest_type": "extension"}]
        }
        db.save_ivrs([initial_ivr])
        
        # Attempt to edit it to introduce duplicates
        edit_data = MultiDict([
            ("name", "billing_menu_updated"),
            ("prompt_id", "prompt_billing"),
            ("timeout", "10"),
            ("loops", "3"),
            ("fail_mode", "hangup"),
            ("fail_ext", ""),
            ("mapping_keys[]", "2"),
            ("mapping_keys[]", "2"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dest_types[]", "extension"),
            ("mapping_dests[]", "5001"),
            ("mapping_dests[]", "5002")
        ])
        response = self.client.post("/ivr/edit/7003", data=edit_data)
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Duplicate DTMF keys", data["msg"])
        
        # Verify initial state remains unmodified
        ivrs = db.get_ivrs()
        self.assertEqual(len(ivrs), 1)
        self.assertEqual(ivrs[0]["name"], "billing_menu")
        self.assertEqual(len(ivrs[0]["mappings"]), 1)

    def test_global_favicon_route_returns_image(self):
        # Mock send_from_directory to verify it routes correctly
        with mock.patch("app.send_from_directory") as mock_send:
            mock_send.return_value = "image_mock"
            response = self.client.get("/LOGO.jpg")
            self.assertEqual(response.data.decode("utf-8"), "image_mock")
            mock_send.assert_called_once_with('/var/www/html', 'LOGO.jpg', mimetype='image/jpeg')

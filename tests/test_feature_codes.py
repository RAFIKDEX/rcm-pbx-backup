import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock
from flask import session

import db
import rcm_queue_db


class FeatureCodesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.old_main_db = db.DB_PATH
        cls.old_queue_db = rcm_queue_db.DB_PATH
        
        # Override paths to avoid modifying the real DBs
        db.DB_PATH = os.path.join(cls.tmpdir.name, "main.db")
        rcm_queue_db.DB_PATH = os.path.join(cls.tmpdir.name, "queue.db")
        
        # Reload app module with new db paths
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.flask_app = cls.app_module.app
        cls.flask_app.config.update(TESTING=True, SECRET_KEY="testsecret")

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.old_main_db
        rcm_queue_db.DB_PATH = cls.old_queue_db
        cls.tmpdir.cleanup()

    def setUp(self):
        # Freshly initialize database structure and seed data
        db.init_db()
        rcm_queue_db.init_queue_db()
        self.client = self.flask_app.test_client()
        self.patcher = mock.patch("asterisk_helper.run_asterisk_cmd", return_value="Success")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def login_client(self, username, role="agent"):
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = username
            sess['role'] = role

    def test_database_seeding(self):
        # Verify default feature codes are seeded correctly
        features = db.get_all_feature_codes()
        self.assertGreater(len(features), 0)
        
        # Verify presence of key feature codes
        feat_names = [f["feature_name"] for f in features]
        self.assertIn("My Voicemail", feat_names)
        self.assertIn("DND Activate", feat_names)
        self.assertIn("Listen Spy", feat_names)
        self.assertIn("Queue Login", feat_names)
        self.assertIn("Forward Always Activate", feat_names)

        # Verify seeded users
        self.assertEqual(db.get_user_role("admin"), "admin")
        self.assertEqual(db.get_user_role("supervisor"), "supervisor")
        self.assertEqual(db.get_user_role("agent"), "agent")

    def test_gui_list_endpoint(self):
        self.login_client("admin", "admin")
        response = self.client.get('/feature-codes')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Feature Codes Management", response.data)
        self.assertIn(b"My Voicemail", response.data)
        self.assertIn(b"DND Activate", response.data)

    @mock.patch('asterisk_helper.run_asterisk_cmd')
    def test_update_feature_code(self, mock_asterisk):
        self.login_client("admin", "admin")
        
        # Find ID of "My Voicemail"
        features = db.get_all_feature_codes()
        my_vm = next(f for f in features if f["feature_name"] == "My Voicemail")
        
        # Update code only
        response = self.client.post('/feature-codes/update', data={
            "id": my_vm["id"],
            "name": "My Voicemail",
            "code": "*999"
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify in database
        updated = db.get_feature_by_name("My Voicemail")
        self.assertEqual(updated["feature_code"], "*999")
        # Description and permissions must remain unchanged (seeded defaults)
        self.assertEqual(updated["description"], "Access personal voicemail inbox")
        self.assertEqual(updated["permissions"], "admin,supervisor,agent")
        self.assertEqual(updated["enabled"], 1)

    def test_update_duplicate_feature_code(self):
        self.login_client("admin", "admin")
        
        # Get two features
        features = db.get_all_feature_codes()
        my_vm = next(f for f in features if f["feature_name"] == "My Voicemail")
        dnd_act = next(f for f in features if f["feature_name"] == "DND Activate")
        
        # Try to set "My Voicemail" code to DND Activate's code (*37)
        response = self.client.post('/feature-codes/update', data={
            "id": my_vm["id"],
            "name": "My Voicemail",
            "code": dnd_act["feature_code"]
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"is already used by", response.data)
        
        # Verify database remained unchanged for My Voicemail
        vm_db = db.get_feature_by_name("My Voicemail")
        self.assertNotEqual(vm_db["feature_code"], dnd_act["feature_code"])

    @mock.patch('asterisk_helper.send_ami_command')
    def test_call_spy_permissions(self, mock_ami):
        # 1. Test Agent role (should be denied)
        self.login_client("agent_user", "agent")
        response = self.client.post('/call-center/supervisor/control', json={
            "command": "chan_spy",
            "spy_ext": "5001",
            "target": "5002",
            "spy_mode": "listen"
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"is not allowed to monitor", response.data)

        # 2. Setup target extension permissions in DB
        db.delete_extension("5002")
        self.assertTrue(db.add_extension({
            "ext": "5002",
            "enabled": 1,
            "name": "Target Bob",
            "callerid_number": "5002",
            "secret": "secret",
            "max_contacts": 3,
            "max_expiration": 120,
            "ring_time": 60,
            "vm_enabled": 0,
            "vm_password": "1234",
            "record_mode": "noo",
            "direct_media": 0,
            "nat": 0,
            "followme": [],
            "mobile": "",
            "allow_spy": 1
        }))

        # 3. Test Supervisor role (should succeed)
        db.set_spy_permissions_for_target("5002", ["5001"])
        self.login_client("super_user", "supervisor")
        mock_ami.return_value = "Success"
        response = self.client.post('/call-center/supervisor/control', json={
            "command": "chan_spy",
            "spy_ext": "5001",
            "target": "5002",
            "spy_mode": "listen"
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_ami.called)

    @mock.patch('asterisk_helper.send_ami_command')
    def test_target_extension_allow_spy_permission(self, mock_ami):
        self.login_client("super_user", "supervisor")
        mock_ami.return_value = "Success"

        # Create extension with allow_spy = 0 (disabled)
        db.delete_extension("5003")
        self.assertTrue(db.add_extension({
            "ext": "5003",
            "enabled": 1,
            "name": "Target Alice",
            "callerid_number": "5003",
            "secret": "secret",
            "max_contacts": 3,
            "max_expiration": 120,
            "ring_time": 60,
            "vm_enabled": 0,
            "vm_password": "1234",
            "record_mode": "noo",
            "direct_media": 0,
            "nat": 0,
            "followme": [],
            "mobile": "",
            "allow_spy": 0
        }))
        db.set_spy_permissions_for_target("5003", ["5001"])

        # Spy request on extension that has disabled spyable status (should return 403)
        response = self.client.post('/call-center/supervisor/control', json={
            "command": "chan_spy",
            "spy_ext": "5001",
            "target": "5003",
            "spy_mode": "listen"
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"has call monitoring disabled", response.data)

    @mock.patch('app.get_agent_queue_membership')
    @mock.patch('asterisk_helper.send_ami_command')
    def test_queue_actions_permissions(self, mock_ami, mock_membership):
        # Setup mock membership
        mock_membership.return_value = ("NOT_MEMBER", None)
        
        # 1. Test dynamic queue join with 'agent' role
        # Queue Login has permission 'admin,supervisor,agent' by default, so it should succeed
        self.login_client("agent_user", "agent")
        response = self.client.post('/queues/6500/agents/join', data={"agent": "5001"})
        self.assertEqual(response.status_code, 200)

        # 2. Modify "Queue Login" permissions in DB to supervisor/admin only
        q_login = db.get_feature_by_name("Queue Login")
        db.update_feature_code(
            q_login["id"], q_login["feature_code"], 1, 
            q_login["description"], "admin,supervisor"
        )

        # 3. Request join again with 'agent' role (should return 403)
        response = self.client.post('/queues/6500/agents/join', data={"agent": "5001"})
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"is not authorized to join queues", response.data)


if __name__ == '__main__':
    unittest.main()

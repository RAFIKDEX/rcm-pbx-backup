import io
import os
import shutil
import tempfile
import unittest

import app
import db


class UserManagementQaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_db_path = db.DB_PATH
        cls.original_log_path = db.PBX_OPERATION_LOG_FILE

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        db.PBX_OPERATION_LOG_FILE = cls.original_log_path

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="rcm_user_management_qa_")
        self.test_db = os.path.join(self.temp_dir, "rcm.db")
        shutil.copy2(self.original_db_path, self.test_db)
        db.DB_PATH = self.test_db
        db.PBX_OPERATION_LOG_FILE = os.path.join(self.temp_dir, "operations.json")
        db.init_db()
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        response = self.client.post("/", data={"username": "admin", "password": "admin123"})
        self.assertEqual(response.status_code, 302)
        self.security_headers = {"X-Enforce-Security": "1"}

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db.PBX_OPERATION_LOG_FILE = self.original_log_path
        shutil.rmtree(self.temp_dir)

    def csrf_token(self):
        with self.client.session_transaction() as current_session:
            return current_session["csrf_token"]

    def post(self, path, data=None, follow_redirects=True):
        payload = dict(data or {})
        payload.setdefault("csrf_token", self.csrf_token())
        return self.client.post(
            path,
            data=payload,
            headers=self.security_headers,
            follow_redirects=follow_redirects,
        )

    def agent_privilege_id(self):
        return next(item["id"] for item in db.get_privileges_list() if item.get("system_key") == "agent")

    def create_management_user(self, username="qa_user", email="qa_user@example.com"):
        response = self.post("/users/add", {
            "username": username,
            "email": email,
            "password": "ValidPass8",
            "confirm_password": "ValidPass8",
            "privilege_id": self.agent_privilege_id(),
            "status": "enabled",
        })
        self.assertEqual(response.status_code, 200)
        user = db.get_user_by_username(username)
        self.assertIsNotNone(user)
        return user

    def test_user_validation_and_form_state(self):
        response = self.post("/users/add", {
            "username": "keep_me",
            "email": "keep@example.com",
            "password": "ValidPass8",
            "confirm_password": "Mismatch8",
            "privilege_id": self.agent_privilege_id(),
            "status": "enabled",
        })
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn('value = values.username', html)
        self.assertIn('"username": "keep_me"', html)
        self.assertIn('"email": "keep@example.com"', html)

    def test_user_rejects_invalid_email_status_privilege_and_duplicate_email(self):
        privilege_id = self.agent_privilege_id()
        base = {
            "password": "ValidPass8",
            "confirm_password": "ValidPass8",
            "privilege_id": privilege_id,
            "status": "enabled",
        }
        for username, email, status, selected_privilege in (
            ("bad_email", "a@b.<img>", "enabled", privilege_id),
            ("bad_status", "status@example.com", "corrupt", privilege_id),
            ("bad_privilege", "privilege@example.com", "enabled", 999999),
        ):
            payload = dict(base, username=username, email=email, status=status, privilege_id=selected_privilege)
            response = self.post("/users/add", payload)
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(db.get_user_by_username(username))

        self.create_management_user("email_owner", "same@example.com")
        response = self.post("/users/add", dict(base, username="email_duplicate", email="SAME@example.com"))
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(db.get_user_by_username("email_duplicate"))

    def test_user_edit_rejects_invalid_values(self):
        user = self.create_management_user()
        response = self.post(f"/users/edit/{user['id']}", {
            "username": "qa_user",
            "email": "qa_user@example.com",
            "privilege_id": "invalid",
            "status": "enabled",
        })
        self.assertEqual(response.status_code, 400)
        response = self.post(f"/users/edit/{user['id']}", {
            "username": "qa_user",
            "email": "qa_user@example.com",
            "privilege_id": self.agent_privilege_id(),
            "status": "corrupt",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db.get_user_by_id(user["id"])["status"], "enabled")

    def test_csrf_and_bulk_action_are_enforced(self):
        user = self.create_management_user()
        response = self.client.post(
            "/users/bulk-toggle",
            data={"user_ids": user["id"], "action": "disable"},
            headers=self.security_headers,
        )
        self.assertEqual(response.status_code, 403)
        response = self.post("/users/bulk-toggle", {"user_ids": user["id"], "action": "mistyped"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.get_user_by_id(user["id"])["status"], "enabled")

    def test_csv_import_uses_normal_validation_and_requires_password(self):
        content = (
            "Username,Email,Password\n"
            "csv_good,csv_good@example.com,ValidPass8\n"
            "csv_bad_email,not-email,ValidPass8\n"
            "csv_bad_name!,csv_bad_name@example.com,ValidPass8\n"
            "csv_no_password,csv_no_password@example.com,\n"
        )
        response = self.post("/users/import-csv", {
            "default_privilege_id": self.agent_privilege_id(),
            "csv_file": (io.BytesIO(content.encode()), "users.csv"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(db.get_user_by_username("csv_good"))
        self.assertIsNone(db.get_user_by_username("csv_bad_email"))
        self.assertIsNone(db.get_user_by_username("csv_bad_name!"))
        self.assertIsNone(db.get_user_by_username("csv_no_password"))

    def test_activity_requires_an_existing_management_user(self):
        response = self.client.get("/api/users/missing_user/activity", headers=self.security_headers)
        self.assertEqual(response.status_code, 404)

    def test_privilege_rejects_tampered_fields_and_malformed_json(self):
        response = self.post("/privileges/save", {
            "name": "Invalid Permission",
            "perm_fake_module:own_everything": "on",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(next((item for item in db.get_privileges_list() if item["name"] == "Invalid Permission"), None))

        for payload in (
            {"name": "Broken JSON 1", "permissions": [{"module": "users"}]},
            {"name": "Broken JSON 2", "permissions": "not-a-list"},
        ):
            response = self.client.post(
                "/privileges/save",
                json=payload,
                headers={**self.security_headers, "X-CSRF-Token": self.csrf_token()},
            )
            self.assertEqual(response.status_code, 400)

    def test_privilege_rejects_unknown_scope_items(self):
        response = self.post("/privileges/save", {
            "name": "Invalid Scope",
            "perm_dashboard:view": "on",
            "scope_mode_queue_live": "selected",
            "scope_items_queue_live": "missing-queue",
            "scope_mode_queue_stats": "all",
            "scope_mode_cdr_reports": "all",
            "scope_mode_call_records": "all",
        })
        self.assertEqual(response.status_code, 400)

    def test_view_only_privilege_uses_view_controls_and_blocks_writes(self):
        success, privilege_id, message = db.save_privilege_atomic(
            None,
            "QA View Only",
            "",
            "agent",
            [("privileges", "view"), ("users", "view")],
            {"settings": {}, "items": {}},
            caller_system_key="super_admin",
        )
        self.assertTrue(success, message)
        success, _user_id, message = db.create_user(
            "qa_view_only", "ValidPass8", "view_only@example.com", privilege_id, "enabled",
            caller_system_key="super_admin",
        )
        self.assertTrue(success, message)
        client = app.app.test_client()
        self.assertEqual(client.post("/", data={"username": "qa_view_only", "password": "ValidPass8"}).status_code, 302)
        html = client.get("/privileges", headers=self.security_headers).get_data(as_text=True)
        self.assertIn('title="View"', html)
        self.assertNotIn('title="Edit"', html)
        self.assertNotIn('id="addPrivilegeBtn"', html)

    def test_management_permissions_do_not_require_hidden_legacy_role(self):
        success, privilege_id, message = db.save_privilege_atomic(
            None,
            "QA Management Reader",
            "",
            "agent",
            [("privileges", "view"), ("users", "view")],
            {"settings": {}, "items": {}},
            caller_system_key="super_admin",
        )
        self.assertTrue(success, message)
        success, _user_id, message = db.create_user(
            "qa_management_reader", "ValidPass8", "reader@example.com", privilege_id, "enabled",
            caller_system_key="super_admin",
        )
        self.assertTrue(success, message)
        client = app.app.test_client()
        client.post("/", data={"username": "qa_management_reader", "password": "ValidPass8"})
        self.assertEqual(client.get("/users", headers=self.security_headers).status_code, 200)
        self.assertEqual(client.get("/privileges", headers=self.security_headers).status_code, 200)

    def test_ui_has_supported_page_sizes_and_accessible_modals(self):
        for path in ("/users", "/privileges"):
            html = self.client.get(path, headers=self.security_headers).get_data(as_text=True)
            for size in (10, 20, 30, 50, 70, 100):
                self.assertIn(f'value="{size}"', html)
            self.assertIn('role="dialog"', html)
            self.assertIn('aria-modal="true"', html)
            self.assertIn("e.key === 'Escape'", html)

    def test_users_pagination_is_clamped(self):
        html = self.client.get("/users?page=999&per_page=7", headers=self.security_headers).get_data(as_text=True)
        self.assertIn("Page 1 of 1", html)
        self.assertIn('<option value="20" selected', html)
        empty = self.client.get("/users?search=definitely-not-present", headers=self.security_headers).get_data(as_text=True)
        self.assertIn("Page 1 of 1", empty)

    def test_privilege_names_are_not_embedded_in_inline_javascript(self):
        response = self.post("/privileges/save", {
            "name": "O'Brien",
            "perm_dashboard:view": "on",
            "scope_mode_queue_live": "all",
            "scope_mode_queue_stats": "all",
            "scope_mode_cdr_reports": "all",
            "scope_mode_call_records": "all",
        })
        self.assertEqual(response.status_code, 200)
        html = self.client.get("/privileges", headers=self.security_headers).get_data(as_text=True)
        self.assertNotIn("openDuplicatePrivilegeModal(", html.split("</tbody>")[0])
        self.assertNotIn("confirmDeletePrivilege(", html.split("</tbody>")[0])


if __name__ == "__main__":
    unittest.main()

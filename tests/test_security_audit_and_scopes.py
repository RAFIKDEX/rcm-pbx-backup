import unittest
import json
import app
import db
from unittest import mock
from app import app as flask_app, audit_details, audit_changes, _is_sensitive_key

class SecurityAuditAndScopesTestCase(unittest.TestCase):
    def setUp(self):
        flask_app.config['TESTING'] = True
        self.client = flask_app.test_client()
        # Ensure fresh in-memory / test state if applicable

    def test_sensitive_key_detection(self):
        """Verify that sensitive keys are detected regardless of case or wording."""
        sensitive_samples = [
            "password", "secret", "vm_password", "SIP Password", "Voicemail PIN",
            "auth_id", "token", "otp", "cookie", "csrf_token", "api_key", "user_hash"
        ]
        for key in sensitive_samples:
            self.assertTrue(_is_sensitive_key(key), f"Key '{key}' should be marked as sensitive.")

        non_sensitive_samples = [
            "username", "extension", "name", "email", "caller_id", "status"
        ]
        for key in non_sensitive_samples:
            self.assertFalse(_is_sensitive_key(key), f"Key '{key}' should NOT be marked as sensitive.")

    def test_audit_details_masks_passwords_and_pins(self):
        """Verify that audit_details completely masks sensitive values."""
        res = audit_details(
            extension="1001",
            name="Test User",
            password="SuperSecretPassword123!",
            secret="MySipSecret999",
            vm_password="4321",
            sip_password="AnotherSipSecret"
        )
        self.assertIn("Extension=1001", res)
        self.assertIn("Name=Test User", res)
        self.assertNotIn("SuperSecretPassword123!", res)
        self.assertNotIn("MySipSecret999", res)
        self.assertNotIn("4321", res)
        self.assertNotIn("AnotherSipSecret", res)
        self.assertIn("Password=******", res)
        self.assertIn("Secret=******", res)
        self.assertIn("Vm Password=******", res)
        self.assertIn("Sip Password=******", res)

    def test_audit_changes_masks_sensitive_setting_diffs(self):
        """Verify that audit_changes masks old and new values for sensitive fields."""
        before = {
            "name": "Alice",
            "SIP Password": "OldPassword123",
            "Voicemail PIN": "1111",
            "secret": "OldSecret"
        }
        after = {
            "name": "Alice Updated",
            "SIP Password": "NewPassword456",
            "Voicemail PIN": "2222",
            "secret": "NewSecret"
        }
        changes = audit_changes(before, after, ["name", "SIP Password", "Voicemail PIN", "secret"])
        
        # Find changes by setting
        change_map = {c["setting"]: c for c in changes}
        
        self.assertEqual(change_map["name"]["old"], "Alice")
        self.assertEqual(change_map["name"]["new"], "Alice Updated")
        
        self.assertEqual(change_map["SIP Password"]["old"], "******")
        self.assertEqual(change_map["SIP Password"]["new"], "******")
        
        self.assertEqual(change_map["Voicemail PIN"]["old"], "******")
        self.assertEqual(change_map["Voicemail PIN"]["new"], "******")
        
        self.assertEqual(change_map["secret"]["old"], "******")
        self.assertEqual(change_map["secret"]["new"], "******")

    def test_log_pbx_operation_sanitizes_changes_list(self):
        """Verify that db.log_pbx_operation masks sensitive items in changes list when stored."""
        raw_changes = [
            {"setting": "callerid", "old": "100", "new": "200"},
            {"setting": "sip password", "old": "raw_old_pw", "new": "raw_new_pw"},
            {"setting": "voicemail pin", "old": "0000", "new": "9999"}
        ]
        db.log_pbx_operation(
            action="Extension Audit Test",
            username="admin",
            ip_address="127.0.0.1",
            status="success",
            message="Testing log sanitization",
            changes=raw_changes,
            module="Extension"
        )
        logs = db.get_pbx_operation_logs(limit=10, module="Extension")
        self.assertTrue(len(logs) > 0)
        latest = logs[0]
        self.assertEqual(latest["action"], "Extension Audit Test")
        
        stored_changes = {c["setting"]: c for c in latest.get("changes", []) if isinstance(c, dict)}
        self.assertEqual(stored_changes["callerid"]["old"], "100")
        self.assertEqual(stored_changes["callerid"]["new"], "200")
        self.assertEqual(stored_changes["sip password"]["old"], "******")
        self.assertEqual(stored_changes["sip password"]["new"], "******")
        self.assertEqual(stored_changes["voicemail pin"]["old"], "******")
        self.assertEqual(stored_changes["voicemail pin"]["new"], "******")

    def test_scope_enforcement_default_none_for_ambiguous(self):
        """Verify that ambiguous or missing scopes default to none (never all)."""
        with flask_app.test_request_context('/'):
            # Simulate a user session without scope setting for 'extensions'
            flask_app.preprocess_request()
            from flask import session
            session['user'] = 'test_scoped_user'
            session['role'] = 'CustomRole'
            session.modified = True
            
            # Monkeypatch get_user_permissions_context to return access with missing scope
            original_get_context = db.get_user_permissions_context
            try:
                db.get_user_permissions_context = lambda username: {
                    "is_super_admin": False,
                    "role_name": "CustomRole",
                    "permissions": {
                        "extensions": {"view": True, "edit": True}
                        # Note: scope_extensions is NOT defined -> ambiguous/missing -> must default to none
                    }
                }
                
                # Check permission with target ID '1001'
                has_perm = app.has_permission("extensions", "edit", scope_id="1001", scope_type="extensions")
                self.assertFalse(has_perm, "Should deny access when scope is ambiguous or not explicitly granted.")
            finally:
                db.get_user_permissions_context = original_get_context

    def test_enforce_security_header_blocks_unauthorized_when_testing(self):
        """Verify that passing X-Enforce-Security header enforces real auth and CSRF even when TESTING=True."""
        response = self.client.post(
            "/extensions/add",
            data={"extension": "9999", "name": "Hack Ext"},
            headers={"X-Enforce-Security": "1"}
        )
        # Without session/CSRF token, should be blocked or redirected to login
        self.assertIn(response.status_code, [302, 400, 401, 403])

    def test_non_super_admin_cannot_modify_or_assign_protected_roles(self):
        """Verify database layer blocks non-Super-Admin accounts from assigning or modifying protected roles."""
        # 1. Create a protected role directly in DB if not existing or test with Super Admin role (id 1)
        success, err = db.update_user(user_id=2, privilege_id=1, caller_system_key="agent_role")
        self.assertFalse(success, "Non-super-admin ('agent_role') should not be able to assign protected role (Super Admin).")
        self.assertIn("Only Super Admin accounts can assign protected roles", err)

        # 2. Attempt modifying a protected privilege with a non-super-admin caller
        success, saved_id, err = db.save_privilege_atomic(
            privilege_id=1,
            name="Super Admin Altered",
            description="Attempted breach",
            legacy_role="admin",
            permissions_list=[("*", "*")],
            scopes_dict={"settings": {}, "items": {}},
            caller_system_key="agent_role"
        )
        self.assertFalse(success, "Non-super-admin ('agent_role') should not be able to modify protected role.")
        self.assertIn("Only Super Admin accounts can modify protected roles", err)

    def test_modifying_endpoints_require_csrf_and_post(self):
        """Verify modifying endpoints reject missing/invalid CSRF tokens when security header is set."""
        action_only_endpoints = [
            "/extensions/delete/101",
            "/users/delete/1",
            "/users/toggle/1",
            "/privileges/save",
            "/privileges/delete/2",
            "/privileges/duplicate/2"
        ]
        form_post_endpoints = [
            "/extensions/add",
            "/extensions/edit/101",
            "/users/add",
            "/users/edit/1"
        ]
        for ep in action_only_endpoints:
            # 1. Attempting GET on POST-only action endpoint should yield 405 Method Not Allowed
            res_get = self.client.get(ep)
            self.assertEqual(res_get.status_code, 405, f"GET request to action endpoint {ep} should be rejected with 405.")

        for ep in action_only_endpoints + form_post_endpoints:
            # 2. Attempting POST without valid CSRF token and with X-Enforce-Security should fail
            res_post = self.client.post(ep, data={"csrf_token": "invalid_token"}, headers={"X-Enforce-Security": "1"})
            self.assertIn(res_post.status_code, [302, 400, 401, 403], f"POST without valid CSRF token to {ep} should be blocked.")

    def test_save_privilege_atomic_preserves_independent_actions(self):
        """Verify that saving one action never silently adds the View action."""
        import time as pytime
        unique_name = f"AutoViewTestRole_{int(pytime.time() * 1000)}"
        success, saved_id, err = db.save_privilege_atomic(
            privilege_id=None,
            name=unique_name,
            description="Testing independent actions",
            legacy_role="agent",
            permissions_list=[("extensions", "edit"), ("queues", "manage_agents")],
            scopes_dict={"settings": {}, "items": {}},
            caller_system_key="super_admin"
        )
        self.assertTrue(success, f"Should successfully save privilege: {err}")
        perms = db.get_privilege_permissions(saved_id)
        perm_set = {(m, a) for m, a in perms}
        self.assertIn(("extensions", "edit"), perm_set)
        self.assertIn(("queues", "manage_agents"), perm_set)
        self.assertNotIn(("extensions", "view"), perm_set)
        self.assertNotIn(("queues", "view"), perm_set)
        if saved_id:
            db.delete_privilege(saved_id)

    def test_get_user_scope_for_type_defaults_none_for_missing_or_invalid(self):
        """Verify get_user_scope_for_type defaults to none for non-super-admin if missing or invalid mode."""
        # Check for non-existent user
        mode, items = db.get_user_scope_for_type(-999, "queue_live")
        self.assertEqual(mode, "none")
        self.assertEqual(items, set())

    def test_queue_call_scope_accepts_any_related_queue_leg(self):
        """A full transferred journey is visible when one related leg is allowed."""
        class FakeConnection:
            def __init__(self):
                self.sql = ""
                self.params = []

            def execute(self, sql, params):
                self.sql = sql
                self.params = list(params)
                return self

            def fetchone(self):
                # Simulates the allowed second leg matching the shared
                # linkedid; the old LIMIT-1 queue lookup could miss it.
                return {"in_scope": 1}

            def close(self):
                pass

        connection = FakeConnection()
        with mock.patch.object(app, "reporting_scope_allowed_queues", return_value={"6502"}), \
             mock.patch.object(app.rcm_queue_db, "get_db_connection", return_value=connection):
            self.assertTrue(app._queue_call_is_in_scope("queue_stats", "linked-call-1"))
        self.assertIn("queue_id IN (?)", connection.sql)
        self.assertEqual(connection.params, ["6502", "6502", "linked-call-1", "linked-call-1"])

    def test_grouped_module_permissions_structure(self):
        """Verify GROUPED_MODULE_PERMISSIONS has all required sections and modules."""
        from app import GROUPED_MODULE_PERMISSIONS
        section_names = [section[0] for section in GROUPED_MODULE_PERMISSIONS]
        expected_sections = [
            "System Status", "Extensions and Trunks", "Call Features", "Call Center",
            "Reports", "PBX Settings", "System Settings", "Maintenance", "User Management"
        ]
        for sec in expected_sections:
            self.assertIn(sec, section_names, f"Section '{sec}' should exist in GROUPED_MODULE_PERMISSIONS.")

    def test_scope_options_api_endpoints(self):
        """Verify scope options endpoints return correct json structure for queue_live and cdr_reports."""
        res_queue = self.client.get('/api/scopes/options/queue_live')
        self.assertEqual(res_queue.status_code, 200)
        data_queue = json.loads(res_queue.data)
        self.assertIn("options", data_queue)

        res_cdr = self.client.get('/api/scopes/options/cdr_reports')
        self.assertEqual(res_cdr.status_code, 200)
        data_cdr = json.loads(res_cdr.data)
        self.assertIn("options", data_cdr)

if __name__ == '__main__':
    unittest.main()

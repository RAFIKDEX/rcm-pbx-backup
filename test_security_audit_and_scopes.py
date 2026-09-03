import unittest
import json
import app
import db
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
                has_perm = app.has_permission("extensions", "edit", target_id="1001", scope_type="extensions")
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

if __name__ == '__main__':
    unittest.main()

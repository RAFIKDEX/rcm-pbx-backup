import unittest
from unittest import mock

import app as app_module
from dex import security as dex_security


class DexRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_testing = app_module.app.config.get("TESTING")
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.context = {"system_key": "super_admin", "permissions": set(), "scopes": {}}

    def tearDown(self):
        app_module.app.config["TESTING"] = self.original_testing

    def login(self, csrf="csrf-test"):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "dex-test"
            session["csrf_token"] = csrf

    def test_pages_require_permissions_on_direct_access(self):
        self.login()
        with mock.patch.object(app_module.db, "get_user_permissions_context", return_value={"system_key": None, "permissions": set(), "scopes": {}}), mock.patch.object(dex_security, "get_permission_context", return_value={"system_key": None, "permissions": set(), "scopes": {}}):
            self.assertEqual(self.client.get("/dex/phones").status_code, 403)
            self.assertEqual(self.client.get("/dex/models").status_code, 403)
            self.assertEqual(self.client.get("/dex/config").status_code, 403)

    def test_super_admin_can_open_all_core_pages(self):
        self.login()
        with mock.patch.object(app_module.db, "get_user_permissions_context", return_value=self.context), mock.patch.object(dex_security, "get_permission_context", return_value=self.context):
            self.assertEqual(self.client.get("/dex/phones").status_code, 200)
            self.assertEqual(self.client.get("/dex/models").status_code, 200)
            self.assertEqual(self.client.get("/dex/config").status_code, 200)

    def test_state_change_requires_strict_csrf(self):
        self.login(csrf="expected")
        with mock.patch.object(app_module.db, "get_user_permissions_context", return_value=self.context), mock.patch.object(dex_security, "get_permission_context", return_value=self.context):
            response = self.client.post("/dex/phones/1/reboot", data={})
        self.assertEqual(response.status_code, 403)

    def test_discovery_rejects_unbounded_public_request(self):
        self.login()
        with mock.patch.object(app_module.db, "get_user_permissions_context", return_value=self.context), mock.patch.object(dex_security, "get_permission_context", return_value=self.context):
            response = self.client.post("/dex/discovery/scan", data={"csrf_token": "csrf-test", "cidr": "0.0.0.0/0"})
        self.assertEqual(response.status_code, 400)

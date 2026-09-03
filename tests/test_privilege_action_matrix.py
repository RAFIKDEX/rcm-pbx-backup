import unittest
from unittest import mock

import app as app_module


def _ctx(module, *actions):
    return {
        "system_key": None,
        "permissions": {(module, action) for action in actions},
        "scopes": {},
    }


class PrivilegeActionMatrixTests(unittest.TestCase):
    def test_permission_actions_are_independent(self):
        cases = [
            (("view",), (True, False, False, False, True)),
            (("edit",), (False, False, True, False, True)),
            (("delete",), (False, False, False, True, True)),
            (("add",), (False, True, False, False, True)),
            (("view", "edit"), (True, False, True, False, True)),
            (("view", "delete"), (True, False, False, True, True)),
            (("edit", "delete"), (False, False, True, True, True)),
            (("add", "edit"), (False, True, True, False, True)),
            (("add", "delete"), (False, True, False, True, True)),
            (("view", "add", "edit", "delete"), (True, True, True, True, True)),
            ((), (False, False, False, False, False)),
        ]
        module = "test_module"
        with mock.patch.object(app_module, "get_current_user_context") as context:
            with app_module.app.test_request_context("/"):
                app_module.session["logged_in"] = True
                for actions, expected in cases:
                    context.return_value = _ctx(module, *actions)
                    actual = (
                        app_module.can_view(module),
                        app_module.can_create(module),
                        app_module.can_edit(module),
                        app_module.can_delete(module),
                        app_module.can_access_module(module),
                    )
                    self.assertEqual(actual, expected, actions)


    def test_edit_user_cannot_delete_or_open_delete_route(self):
        module = "extensions"
        with mock.patch.object(app_module, "get_current_user_context", return_value=_ctx(module, "edit")), \
             mock.patch.object(app_module, "audit_event"), \
             mock.patch.object(app_module.db, "get_user_by_username", return_value={"username": "edit-only", "status": "enabled", "user_type": "management", "role": "agent"}):
            client = app_module.app.test_client()
            with client.session_transaction() as sess:
                sess["logged_in"] = True
                sess["username"] = "edit-only"
            response = client.post(
                "/extensions/delete/999999",
                headers={"X-Enforce-Security": "1"},
            )
            self.assertEqual(response.status_code, 403)


    def test_delete_user_cannot_edit_route(self):
        module = "extensions"
        with mock.patch.object(app_module, "get_current_user_context", return_value=_ctx(module, "delete")), \
             mock.patch.object(app_module, "audit_event"), \
             mock.patch.object(app_module.db, "get_user_by_username", return_value={"username": "delete-only", "status": "enabled", "user_type": "management", "role": "agent"}):
            client = app_module.app.test_client()
            with client.session_transaction() as sess:
                sess["logged_in"] = True
                sess["username"] = "delete-only"
            response = client.get(
                "/extensions/edit/999999",
                headers={"X-Enforce-Security": "1"},
            )
            self.assertEqual(response.status_code, 403)

    def test_user_with_no_module_permissions_cannot_open_module(self):
        module = "extensions"
        with mock.patch.object(app_module, "get_current_user_context", return_value=_ctx(module)), \
             mock.patch.object(app_module, "audit_event"), \
             mock.patch.object(app_module.db, "get_user_by_username", return_value={"username": "none", "status": "enabled", "user_type": "management", "role": "agent"}):
            client = app_module.app.test_client()
            with client.session_transaction() as sess:
                sess["logged_in"] = True
                sess["username"] = "none"
            response = client.get(
                "/extensions",
                headers={"X-Enforce-Security": "1"},
            )
            self.assertEqual(response.status_code, 403)

    def test_unscoped_crud_record_id_does_not_require_scope_definition(self):
        with mock.patch.object(
            app_module, "get_current_user_context", return_value=_ctx("inbound_routes", "edit")
        ):
            with app_module.app.test_request_context("/"):
                app_module.session["logged_in"] = True
                self.assertTrue(
                    app_module.has_permission("inbound_routes", "edit", scope_id="route-123")
                )

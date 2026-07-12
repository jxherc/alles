from unittest import mock

from core import auth
from services.service_manager import ServiceOwnershipError
from tests._client import ApiTest


class SystemServicesApiTest(ApiTest):
    @mock.patch("routes.system.service_manager.list_services")
    def test_lists_only_service_manager_output(self, list_services):
        list_services.return_value = [
            {
                "service_id": "search",
                "name": "managed search",
                "manager": "compose",
                "owned": True,
                "available": True,
                "running": True,
                "actions": ["restart", "start", "stop"],
            }
        ]
        response = self.client.get("/api/system/services")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["services"][0]["service_id"], "search")

    @mock.patch("routes.system.audit.record")
    @mock.patch("routes.system.service_manager.control")
    def test_typed_control_records_audit(self, control, audit_record):
        control.return_value = {"ok": True, "service_id": "search", "action": "restart"}
        response = self.client.post("/api/system/services/search/restart")
        self.assertEqual(response.status_code, 200)
        control.assert_called_once_with("search", "restart")
        self.assertIn(
            "service.restart",
            [call.kwargs["action"] for call in audit_record.call_args_list],
        )

    @mock.patch("routes.system.service_manager.control")
    def test_unknown_action_is_rejected_before_control(self, control):
        response = self.client.post("/api/system/services/search/remove")
        self.assertEqual(response.status_code, 422)
        control.assert_not_called()

    @mock.patch("routes.system.service_manager.control")
    def test_unowned_service_returns_stable_error(self, control):
        control.side_effect = ServiceOwnershipError("ownership marker is missing")
        response = self.client.post("/api/system/services/search/stop")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "service_not_owned")

    @mock.patch("routes.system.service_manager.control")
    def test_control_requires_a_recent_owner_session(self, control):
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                response = self.client.post("/api/system/services/search/restart")
        finally:
            self.client.cookies.clear()
            auth.revoke_token(token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "recent_auth_required")
        control.assert_not_called()

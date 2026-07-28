from unittest import mock

from services.managed_companion_clients import CompanionClientError
from tests._client import ApiTest


class ManagedCompanionApiTests(ApiTest):
    @mock.patch("routes.system.managed_companion_clients.adguard_dashboard")
    def test_adguard_dashboard_is_native_and_read_only(self, dashboard):
        dashboard.return_value = {"connected": True, "stats": {"num_dns_queries": 4}}
        response = self.client.get("/api/system/companions/adguard-home/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stats"]["num_dns_queries"], 4)

    @mock.patch("routes.system.managed_companion_clients.set_adguard_filtering")
    def test_adguard_filtering_is_typed(self, filtering):
        filtering.return_value = {"ok": True, "enabled": False, "interval": 12}
        response = self.client.put(
            "/api/system/companions/adguard-home/filtering",
            json={"enabled": False, "interval": 12},
        )
        self.assertEqual(response.status_code, 200)
        filtering.assert_called_once_with(False, 12)

    @mock.patch("routes.system.managed_companion_clients.change_adguard_rewrite")
    def test_adguard_rewrite_has_bounded_actions(self, rewrite):
        rewrite.return_value = {"ok": True}
        response = self.client.post(
            "/api/system/companions/adguard-home/rewrites/add",
            json={"domain": "home.example", "answer": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        rewrite.assert_called_once_with(
            "add", "home.example", "127.0.0.1", enabled=True
        )
        invalid = self.client.post(
            "/api/system/companions/adguard-home/rewrites/update",
            json={"domain": "home.example", "answer": "127.0.0.1"},
        )
        self.assertEqual(invalid.status_code, 422)

    @mock.patch("routes.system.managed_companion_clients.connect_npm")
    def test_npm_login_secret_is_not_returned(self, connect):
        connect.return_value = {
            "connected": True,
            "identity": "owner@example.test",
            "expires": "later",
        }
        response = self.client.post(
            "/api/system/companions/nginx-proxy-manager/connect",
            json={"identity": "owner@example.test", "secret": "private password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private password", response.text)
        connect.assert_called_once_with("owner@example.test", "private password")

    @mock.patch("routes.system.managed_companion_clients.create_npm_proxy_host")
    def test_npm_proxy_host_has_typed_destination(self, create):
        create.return_value = {"id": 7, "enabled": True}
        response = self.client.post(
            "/api/system/companions/nginx-proxy-manager/proxy-hosts",
            json={
                "domain_names": ["home.example"],
                "forward_scheme": "http",
                "forward_host": "127.0.0.1",
                "forward_port": 6769,
            },
        )
        self.assertEqual(response.status_code, 200)
        create.assert_called_once_with(
            domain_names=["home.example"],
            forward_scheme="http",
            forward_host="127.0.0.1",
            forward_port=6769,
            certificate_id=0,
            ssl_forced=False,
        )

    @mock.patch("routes.system.managed_companion_clients.npm_dashboard")
    def test_companion_errors_are_explicit(self, dashboard):
        dashboard.side_effect = CompanionClientError("Nginx Proxy Manager is not connected")
        response = self.client.get(
            "/api/system/companions/nginx-proxy-manager/dashboard"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "managed_companion_api_failed")

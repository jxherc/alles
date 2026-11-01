import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import managed_companion_clients as clients


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.content = b"" if payload is None else json.dumps(payload).encode()

    def json(self):
        return self._payload


class Requester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class ManagedCompanionClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alles-companion-clients-")
        self.root = Path(self.temp.name)
        self.patches = [
            mock.patch("services.managed_companion_clients.data_dir", return_value=self.root),
            mock.patch("services.secretstore._KEY_FILE", self.root / "secret.key"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def test_adguard_dashboard_uses_basic_auth_and_bounded_query_log(self):
        clients.save_adguard_credentials("owner", "private password")
        requester = Requester(
            [
                Response(payload={"dns_addresses": ["0.0.0.0"]}),
                Response(payload={"num_dns_queries": 50, "num_blocked_filtering": 12}),
                Response(payload={"enabled": True, "interval": 24}),
                Response(payload=[{"domain": "one.test", "answer": "127.0.0.1"}]),
                Response(payload={"data": [{"question": {"name": "one.test"}}] * 30}),
            ]
        )
        result = clients.adguard_dashboard(requester=requester)
        self.assertEqual(result["stats"]["num_dns_queries"], 50)
        self.assertEqual(len(result["querylog"]), 20)
        self.assertEqual(requester.calls[-1][2]["params"], {"limit": 20})
        self.assertEqual(requester.calls[0][2]["auth"], ("owner", "private password"))

    def test_adguard_mutations_are_typed(self):
        clients.save_adguard_credentials("owner", "private password")
        requester = Requester([Response(payload={}), Response(payload={})])
        clients.set_adguard_filtering(True, 24, requester=requester)
        clients.change_adguard_rewrite("add", "Home.Example", "127.0.0.1", requester=requester)
        self.assertEqual(requester.calls[0][2]["json"], {"enabled": True, "interval": 24})
        self.assertEqual(
            requester.calls[1][2]["json"],
            {"domain": "home.example", "answer": "127.0.0.1", "enabled": True},
        )

    def test_npm_connect_seals_token_and_never_stores_password(self):
        requester = Requester(
            [Response(payload={"token": "jwt-secret", "expires": "2026-08-01T00:00:00Z"})]
        )
        result = clients.connect_npm("owner@example.test", "login-password", requester=requester)
        stored = (self.root / "nginx-proxy-manager.credentials.json").read_text("utf-8")
        self.assertTrue(result["connected"])
        self.assertNotIn("jwt-secret", stored)
        self.assertNotIn("login-password", stored)
        self.assertIn('"token":"enc2:', stored)

    def test_npm_dashboard_and_proxy_host_use_bearer_token(self):
        clients.connect_npm(
            "owner@example.test",
            "login-password",
            requester=Requester([Response(payload={"token": "jwt-secret"})]),
        )
        requester = Requester(
            [
                Response(payload=[{"id": 1, "domain_names": ["home.example"]}]),
                Response(payload=[{"id": 2, "nice_name": "home.example"}]),
                Response(payload={"id": 3, "enabled": True}),
            ]
        )
        result = clients.npm_dashboard(requester=requester)
        created = clients.create_npm_proxy_host(
            domain_names=["home.example", "home.example"],
            forward_scheme="http",
            forward_host="127.0.0.1",
            forward_port=6769,
            requester=requester,
        )
        self.assertEqual(len(result["proxy_hosts"]), 1)
        self.assertEqual(created["id"], 3)
        self.assertEqual(requester.calls[-1][2]["headers"]["Authorization"], "Bearer jwt-secret")
        self.assertEqual(requester.calls[-1][2]["json"]["domain_names"], ["home.example"])

    def test_npm_first_admin_is_created_sealed_and_connected(self):
        requester = Requester(
            [
                Response(payload={"status": "OK", "setup": False}),
                Response(status_code=201, payload={"id": 1}),
                Response(payload={"token": "jwt-secret", "expires": "2099-01-01T00:00:00Z"}),
            ]
        )
        result = clients.setup_npm_admin(
            "admin@alles.local", "generated-password", requester=requester
        )
        self.assertTrue(result["created"])
        body = requester.calls[1][2]["json"]
        self.assertEqual(body["roles"], ["admin"])
        self.assertEqual(body["auth"], {"type": "password", "secret": "generated-password"})
        stored = (self.root / "nginx-proxy-manager.admin.json").read_text("utf-8")
        self.assertNotIn("generated-password", stored)
        self.assertTrue((self.root / "nginx-proxy-manager.credentials.json").is_file())

    def test_npm_first_admin_skipped_when_already_set_up(self):
        requester = Requester([Response(payload={"status": "OK", "setup": True})])
        result = clients.setup_npm_admin(
            "admin@alles.local", "generated-password", requester=requester
        )
        self.assertFalse(result["created"])
        self.assertEqual(len(requester.calls), 1)
        self.assertFalse((self.root / "nginx-proxy-manager.admin.json").exists())

    def test_npm_failed_first_admin_leaves_no_stored_password(self):
        requester = Requester(
            [Response(payload={"setup": False}), Response(status_code=400, payload={})]
        )
        with self.assertRaises(clients.CompanionClientError):
            clients.setup_npm_admin("admin@alles.local", "generated-password", requester=requester)
        self.assertFalse((self.root / "nginx-proxy-manager.admin.json").exists())

    def test_npm_expired_token_signs_in_again_with_the_stored_admin(self):
        clients.setup_npm_admin(
            "admin@alles.local",
            "generated-password",
            requester=Requester(
                [
                    Response(payload={"setup": False}),
                    Response(status_code=201, payload={"id": 1}),
                    Response(payload={"token": "old-token", "expires": "2020-01-01T00:00:00Z"}),
                ]
            ),
        )
        requester = Requester(
            [
                Response(payload={"token": "new-token", "expires": "2099-01-01T00:00:00Z"}),
                Response(payload=[]),
                Response(payload=[]),
            ]
        )
        clients.npm_dashboard(requester=requester)
        self.assertEqual(requester.calls[0][2]["json"]["secret"], "generated-password")
        self.assertEqual(requester.calls[1][2]["headers"]["Authorization"], "Bearer new-token")

    def test_npm_expired_token_without_admin_is_left_alone(self):
        clients.connect_npm(
            "owner@example.test",
            "login-password",
            requester=Requester(
                [Response(payload={"token": "jwt-secret", "expires": "2020-01-01T00:00:00Z"})]
            ),
        )
        requester = Requester([Response(payload=[]), Response(payload=[])])
        clients.npm_dashboard(requester=requester)
        self.assertEqual(requester.calls[0][2]["headers"]["Authorization"], "Bearer jwt-secret")

    def test_clear_credentials_keeps_generated_admin_only_on_request(self):
        for name in ("nginx-proxy-manager.credentials.json", "nginx-proxy-manager.admin.json"):
            (self.root / name).write_text("{}", "utf-8")
        clients.clear_credentials("nginx-proxy-manager", keep_admin=True)
        self.assertFalse((self.root / "nginx-proxy-manager.credentials.json").exists())
        self.assertTrue((self.root / "nginx-proxy-manager.admin.json").exists())
        clients.clear_credentials("nginx-proxy-manager")
        self.assertFalse((self.root / "nginx-proxy-manager.admin.json").exists())

    def test_rejected_credentials_never_leak_response_body(self):
        requester = Requester([Response(status_code=401, payload={"message": "secret detail"})])
        with self.assertRaisesRegex(clients.CompanionClientError, "credentials were rejected"):
            clients.connect_npm("owner@example.test", "login-password", requester=requester)


if __name__ == "__main__":
    unittest.main()

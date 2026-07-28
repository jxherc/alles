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
        clients.change_adguard_rewrite(
            "add", "Home.Example", "127.0.0.1", requester=requester
        )
        self.assertEqual(
            requester.calls[0][2]["json"], {"enabled": True, "interval": 24}
        )
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

    def test_rejected_credentials_never_leak_response_body(self):
        requester = Requester([Response(status_code=401, payload={"message": "secret detail"})])
        with self.assertRaisesRegex(clients.CompanionClientError, "credentials were rejected"):
            clients.connect_npm("owner@example.test", "login-password", requester=requester)


if __name__ == "__main__":
    unittest.main()

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.access_middleware import HostGuardMiddleware, PublicHttpsMiddleware


class PublicHttpsMiddlewareTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.get("/")
        def root():
            return {"ok": True}

        app.add_middleware(PublicHttpsMiddleware)
        self.app = app

    def test_cleartext_public_request_is_rejected(self):
        response = TestClient(self.app, base_url="http://alles.example").get("/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "HTTPS required for public access")

    def test_https_request_is_allowed(self):
        response = TestClient(self.app, base_url="https://alles.example").get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})


class HostGuardMiddlewareTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.get("/")
        def root():
            return {"ok": True}

        @app.websocket("/ws")
        async def websocket_endpoint(websocket):
            await websocket.accept()
            await websocket.close()

        app.add_middleware(
            HostGuardMiddleware,
            allowed_hosts=("alles.example", "*.alles.example", "[::1]"),
        )
        self.client = TestClient(app)

    def test_exact_host_and_port_are_allowed(self):
        self.assertEqual(
            self.client.get("/", headers={"Host": "alles.example:8000"}).status_code,
            200,
        )

    def test_approved_subdomain_is_allowed(self):
        self.assertEqual(
            self.client.get("/", headers={"Host": "calendar.alles.example"}).status_code,
            200,
        )

    def test_bracketed_ipv6_and_port_are_allowed(self):
        self.assertEqual(
            self.client.get("/", headers={"Host": "[::1]:8000"}).status_code,
            200,
        )

    def test_untrusted_or_malformed_host_is_rejected(self):
        for host in (
            "evil.example",
            "alles.example@evil.example",
            "alles.example:99999",
            "[::1",
            "::1",
        ):
            with self.subTest(host=host):
                self.assertEqual(
                    self.client.get("/", headers={"Host": host}).status_code,
                    400,
                )

    def test_untrusted_websocket_host_is_rejected_before_upgrade(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/ws", headers={"Host": "evil.example"}):
                pass
        self.assertEqual(caught.exception.code, 1008)

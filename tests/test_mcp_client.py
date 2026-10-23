import asyncio
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import httpx

from services import mcp_client, mcp_oauth
from tests.fixtures.fake_mcp import Handler

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp.py")


def stdio(era):
    return mcp_client.StdioClient(
        sys.executable, ["-I", FAKE, era], {"PATH": os.environ.get("PATH", "")}
    )


class StdioTests(unittest.TestCase):
    def talk(self, era):
        async def go():
            client = stdio(era)
            try:
                await client.open()
                tools = [t["name"] for t in await client.list_tools()]
                return (
                    client.era,
                    client.version,
                    tools,
                    await client.call_tool("echo", {"text": "hi"}),
                )
            finally:
                await client.aclose()

        return asyncio.run(go())

    def test_modern_servers_skip_the_handshake(self):
        era, version, tools, said = self.talk("modern")
        self.assertEqual((era, version), ("modern", "2026-07-28"))
        self.assertEqual(said, "echo: hi")
        self.assertIn("echo", tools)

    def test_legacy_servers_get_initialize(self):
        era, version, _tools, said = self.talk("legacy")
        self.assertEqual((era, version, said), ("legacy", "2025-11-25", "echo: hi"))

    def test_a_server_that_ignores_discover_still_works(self):
        with mock.patch.object(mcp_client, "DISCOVER_TIMEOUT", 1):
            era, _version, _tools, said = self.talk("silent-legacy")
        self.assertEqual((era, said), ("legacy", "echo: hi"))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/mcp"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Handler.era, Handler.auth, Handler.sse = "modern", False, False
        Handler.seen.clear()
        Handler.sessions.clear()

    def talk(self, token=None, tool="echo", args=None):
        async def go():
            client = mcp_client.HttpClient(self.url, token=token)
            try:
                await client.open()
                tools = [t["name"] for t in await client.list_tools()]
                return client, tools, await client.call_tool(tool, args or {"text": "hi"})
            finally:
                await client.aclose()

        return asyncio.run(go())

    def test_modern_http_sends_the_standard_headers_and_mirrors_params(self):
        client, tools, _ = self.talk()
        self.assertEqual(client.era, "modern")
        self.assertNotIn("broken", tools)  # bad x-mcp-header tools are dropped
        _client, _tools, said = self.talk(tool="region_echo", args={"region": "us-west1"})
        self.assertEqual(said, "region us-west1 header us-west1")
        call = [
            h
            for kind, method, h in (s for s in Handler.seen if s[0] == "mcp")
            if method == "tools/call"
        ][-1]
        self.assertEqual(
            (call["mcp-method"], call["mcp-name"], call["mcp-protocol-version"]),
            ("tools/call", "region_echo", "2026-07-28"),
        )

    def test_legacy_http_uses_a_session(self):
        Handler.era = "legacy"
        client, _tools, said = self.talk()
        self.assertEqual((client.era, said), ("legacy", "echo: hi"))
        later = [
            h
            for kind, method, h in (s for s in Handler.seen if s[0] == "mcp")
            if method == "tools/call"
        ]
        self.assertEqual(later[0]["mcp-session-id"], "s1")
        self.assertEqual(Handler.sessions, {})  # closed with DELETE

    def test_event_stream_answers_are_read(self):
        Handler.sse = True
        _client, _tools, said = self.talk()
        self.assertEqual(said, "echo: hi")

    def test_header_values_are_encoded_when_unsafe(self):
        self.assertEqual(mcp_client._header_value("us-west1"), "us-west1")
        self.assertEqual(mcp_client._header_value("Hello, 世界"), "=?base64?SGVsbG8sIOS4lueVjA==?=")
        self.assertEqual(mcp_client._header_value(" padded "), "=?base64?IHBhZGRlZCA=?=")
        self.assertEqual(
            mcp_client._header_value("=?base64?literal?="), "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?="
        )

    def test_oauth_sign_in_end_to_end(self):
        Handler.auth = True
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": data.name}),
            mock.patch.object(mcp_oauth, "_guard", lambda url: None),
        ):
            with self.assertRaises(mcp_client.AuthNeeded) as need:
                self.talk()
            redirect = "https://alles.example.test/api/mcp/oauth/callback"
            url = asyncio.run(mcp_oauth.begin("srv1", self.url, need.exception.challenge, redirect))
            asked = httpx.URL(url).params
            self.assertEqual(asked["code_challenge_method"], "S256")
            self.assertEqual(asked["resource"], self.url)
            self.assertEqual(asked["scope"], "tools")
            registered = next(
                body for kind, body in [s[:2] for s in Handler.seen] if kind == "register"
            )
            self.assertEqual(registered["application_type"], "web")

            back = httpx.get(url, follow_redirects=False).headers["location"]
            got = httpx.URL(back).params
            # a code that comes back from another issuer is refused
            with self.assertRaises(mcp_oauth.OAuthError):
                asyncio.run(mcp_oauth.finish(got["state"], got["code"], "https://evil.example", ""))
            url = asyncio.run(mcp_oauth.begin("srv1", self.url, need.exception.challenge, redirect))
            got = httpx.URL(httpx.get(url, follow_redirects=False).headers["location"]).params
            self.assertEqual(
                asyncio.run(mcp_oauth.finish(got["state"], got["code"], got["iss"], "")), "srv1"
            )
            self.assertTrue(mcp_oauth.signed_in("srv1"))
            self.assertNotIn(
                "good-token", next(Path(data.name, "mcp", "oauth").iterdir()).read_text()
            )  # sealed

            _client, _tools, said = self.talk(token=lambda: mcp_oauth.token_for("srv1"))
            self.assertEqual(said, "echo: hi")

    def test_challenge_parsing(self):
        parsed = mcp_oauth.challenge(
            'Bearer error="insufficient_scope", scope="a b", resource_metadata="https://x/y"'
        )
        self.assertEqual(
            (parsed["error"], parsed["scope"], parsed["resource_metadata"]),
            ("insufficient_scope", "a b", "https://x/y"),
        )
        self.assertEqual(mcp_oauth.canonical("HTTPS://Mcp.Example.com/"), "https://mcp.example.com")


if __name__ == "__main__":
    unittest.main()


class McpRoutesTests(HttpTests):
    def setUp(self):
        super().setUp()
        from tests._client import ApiTest

        self.api = ApiTest("run")
        self.api.setUp()
        self.addCleanup(self.api.tearDown)
        guard = mock.patch.object(mcp_oauth, "_guard", lambda url: None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_a_remote_server_signs_in_and_connects(self):
        from routes import mcp

        Handler.auth = True
        client = self.api.client
        added = client.post(
            "/api/mcp/servers", json={"name": "fake", "transport": "http", "url": self.url}
        ).json()
        self.addCleanup(lambda: asyncio.run(mcp._disconnect(added["id"])))
        self.assertEqual((added["state"], added["connected"]), ("needs_sign_in", False))
        started = client.post(f"/api/mcp/servers/{added['id']}/sign-in", json={}).json()
        back = httpx.get(started["url"], follow_redirects=False).headers["location"]
        self.assertTrue(back.startswith("http://testserver/api/mcp/oauth/callback?"))
        page = client.get(back.removeprefix("http://testserver"))
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("connected", page.text)
        listed = next(s for s in client.get("/api/mcp/servers").json() if s["id"] == added["id"])
        self.assertEqual(
            (listed["state"], listed["era"], listed["signed_in"]), ("connected", "modern", True)
        )
        self.assertIn("echo", [t["name"] for t in listed["tools"]])

        out = client.post(
            "/api/mcp/call",
            json={"server_id": added["id"], "tool_name": "echo", "arguments": {"text": "yo"}},
        )
        self.assertEqual(out.json()["result"], "echo: yo")

        client.post(f"/api/mcp/servers/{added['id']}/sign-out")
        self.assertFalse(mcp_oauth.signed_in(added["id"]))

    def test_stdio_servers_connect_without_the_mcp_package(self):
        from routes import mcp

        added = self.api.client.post(
            "/api/mcp/servers",
            json={"name": "local", "command": sys.executable, "args": ["-I", FAKE, "legacy"]},
        ).json()
        self.addCleanup(lambda: asyncio.run(mcp._disconnect(added["id"])))
        self.assertEqual((added["state"], added["era"]), ("connected", "legacy"))

    def test_registry_entries_become_ready_to_add_configs(self):
        from routes.mcp import _registry_item

        item = _registry_item(
            {
                "server": {
                    "name": "io.example/notes",
                    "title": "Notes",
                    "description": "notes",
                    "version": "1.2.0",
                    "remotes": [
                        {"type": "streamable-http", "url": "https://mcp.example.test/mcp"},
                        {"type": "sse", "url": "https://x"},
                    ],
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@example/notes",
                            "version": "1.2.0",
                            "transport": {"type": "stdio"},
                            "environmentVariables": [{"name": "NOTES_KEY", "isRequired": True}],
                        }
                    ],
                }
            }
        )
        self.assertEqual(item["remotes"], [{"url": "https://mcp.example.test/mcp", "headers": []}])
        self.assertEqual(
            item["packages"],
            [{"command": "npx", "args": ["-y", "@example/notes@1.2.0"], "env": ["NOTES_KEY"]}],
        )
        self.assertIsNone(
            _registry_item(
                {"server": {"name": "x", "remotes": [{"type": "sse", "url": "https://x"}]}}
            )
        )
        bare = _registry_item(
            {
                "server": {
                    "name": "com.notion/mcp",
                    "remotes": [{"type": "streamable-http", "url": "https://mcp.example.test/mcp"}],
                }
            }
        )
        self.assertEqual(bare["name"], "notion")

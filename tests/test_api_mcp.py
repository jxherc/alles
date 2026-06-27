from unittest import mock

import routes.mcp as mcp
from tests._client import ApiTest


async def _no_connect(*a, **k):
    return False, "connect disabled in tests"  # don't spawn a real stdio subprocess


class McpApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._p = mock.patch.object(mcp, "_connect", _no_connect)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        super().tearDown()

    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/mcp/servers").json(), [])

    def test_registry_shared_via_leaf_module(self):
        # the session/tool registry must BE the leaf services.mcp_registry dicts, so routes.mcp and
        # services.agent_tools share state without a routes<->services import cycle. if someone
        # reintroduces a local `_sessions = {}` in routes/mcp this breaks (and the cycle returns).
        from services import mcp_registry
        self.assertIs(mcp._sessions, mcp_registry.sessions)
        self.assertIs(mcp._tools, mcp_registry.tools)

    def test_add_list_delete(self):
        s = self.client.post(
            "/api/mcp/servers", json={"name": "fs", "command": "echo", "args": ["hi"]}
        ).json()
        self.assertEqual(s["name"], "fs")
        self.assertFalse(s["connected"])
        sid = s["id"]
        self.assertEqual(len(self.client.get("/api/mcp/servers").json()), 1)
        self.assertEqual(self.client.delete(f"/api/mcp/servers/{sid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/mcp/servers").json(), [])

    def test_call_unconnected_400(self):
        r = self.client.post(
            "/api/mcp/call", json={"server_id": "x", "tool_name": "t", "arguments": {}}
        )
        self.assertEqual(r.status_code, 400)

    def test_connect_and_delete_missing_404(self):
        self.assertEqual(self.client.post("/api/mcp/servers/nope/connect").status_code, 404)
        self.assertEqual(self.client.delete("/api/mcp/servers/nope").status_code, 404)

    def test_default_fields(self):
        s = self.client.post("/api/mcp/servers", json={"name": "x", "command": "c"}).json()
        self.assertEqual(s["transport"], "stdio")
        self.assertFalse(s["connected"])
        self.assertEqual(s["tools"], [])
        self.assertEqual(s["args"], [])
        self.assertEqual(s["url"], "")

    def test_sse_transport(self):
        s = self.client.post(
            "/api/mcp/servers",
            json={"name": "remote", "transport": "sse", "url": "http://example.com/mcp"},
        ).json()
        self.assertEqual(s["transport"], "sse")
        self.assertEqual(s["url"], "http://example.com/mcp")
        self.assertFalse(s["connected"])

    def test_presets_list(self):
        presets = self.client.get("/api/mcp/presets").json()
        self.assertEqual(len(presets), 5)
        ids = {p["id"] for p in presets}
        self.assertIn("filesystem", ids)
        self.assertIn("fetch", ids)
        # each preset has expected fields
        for p in presets:
            for field in ("id", "name", "transport", "command", "args", "description"):
                self.assertIn(field, p)

    def test_preset_unknown_404(self):
        r = self.client.post("/api/mcp/presets/doesnotexist")
        self.assertEqual(r.status_code, 404)

    def test_preset_add_server(self):
        # installing a preset creates a server row with the preset's command
        r = self.client.post("/api/mcp/presets/fetch", json={"params": {}})
        self.assertEqual(r.status_code, 200)
        s = r.json()
        self.assertEqual(s["name"], "Fetch")
        self.assertEqual(s["command"], "npx")
        # shows up in list
        self.assertEqual(len(self.client.get("/api/mcp/servers").json()), 1)

    def test_connect_returns_502_when_fails(self):
        sid = self.client.post("/api/mcp/servers", json={"name": "bad", "command": "nope"}).json()[
            "id"
        ]
        r = self.client.post(f"/api/mcp/servers/{sid}/connect")
        self.assertEqual(r.status_code, 502)

    def test_disconnect_always_ok(self):
        # disconnect a nonexistent id — should still return 200 ok
        r = self.client.post("/api/mcp/servers/ghost/disconnect")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

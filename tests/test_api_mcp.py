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

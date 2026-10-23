import asyncio
import json
from unittest import mock

from sqlalchemy import text

import routes.mcp as mcp
from core.database import McpServer
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
        self.assertEqual(s["env"], {})
        self.assertEqual(s["headers"], {})

    def test_credentials_are_encrypted_and_masked(self):
        response = self.client.post(
            "/api/mcp/servers",
            json={
                "name": "private",
                "command": "runner",
                "args": ["--token", "arg-secret", "--mode=safe"],
                "url": "https://user:pass@example.test/mcp?token=url-secret&view=list",
                "env": {"GITHUB_TOKEN": "env-secret", "MODE": "safe"},
                "headers": {"Authorization": "Bearer header-secret", "Accept": "text/event-stream"},
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["args"], ["--token", "***", "--mode=safe"])
        self.assertEqual(body["env"], {"GITHUB_TOKEN": "***", "MODE": "***"})
        self.assertEqual(body["headers"]["Authorization"], "***")
        self.assertEqual(body["headers"]["Accept"], "***")
        self.assertNotIn("url-secret", body["url"])
        db = self.db()
        raw = db.execute(
            text("SELECT args,url,env,headers FROM mcp_servers WHERE id=:id"),
            {"id": body["id"]},
        ).one()
        db.close()
        self.assertTrue(all(value.startswith("enc2:") for value in raw))
        self.assertNotIn("secret", "".join(raw))

    def test_rejects_unsafe_or_oversized_config(self):
        bad_transport = self.client.post(
            "/api/mcp/servers", json={"name": "x", "transport": "pipe"}
        )
        self.assertEqual(bad_transport.status_code, 400)
        bad_env = self.client.post(
            "/api/mcp/servers", json={"name": "x", "env": {"bad key": "value"}}
        )
        self.assertEqual(bad_env.status_code, 400)

    def test_stdio_environment_does_not_inherit_provider_secrets(self):
        with mock.patch.dict(
            "os.environ",
            {"PATH": "/bin", "OPENAI_API_KEY": "ambient", "OTHER": "hidden"},
            clear=True,
        ):
            child = mcp._stdio_env({"GITHUB_TOKEN": "configured"})
        self.assertEqual(child, {"PATH": "/bin", "GITHUB_TOKEN": "configured"})

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

    def test_disabled_tools_are_hidden_and_blocked(self):
        from services import agent_tools, mcp_registry

        class FakeSession:
            async def call_tool(self, name, args):
                return f"called {name}"

        db = self.db()
        srv = McpServer(name="srv", command="c", disabled_tools='["drop"]')
        db.add(srv)
        db.commit()
        sid = srv.id
        db.close()

        mcp_registry.sessions[sid] = FakeSession()
        mcp_registry.tools[sid] = [
            {"name": "keep", "description": "", "schema": {}},
            {"name": "drop", "description": "", "schema": {}},
        ]
        try:
            listed = self.client.get("/api/mcp/servers").json()[0]
            self.assertEqual([t["name"] for t in listed["tools"]], ["keep"])
            self.assertEqual(listed["disabled_tools"], ["drop"])

            self.assertEqual(
                self.client.post(
                    "/api/mcp/call",
                    json={"server_id": sid, "tool_name": "drop", "arguments": {}},
                ).status_code,
                403,
            )
            ok = self.client.post(
                "/api/mcp/call", json={"server_id": sid, "tool_name": "keep", "arguments": {}}
            )
            self.assertEqual(ok.status_code, 200)

            tools = json.loads(asyncio.run(agent_tools._mcp_list_tools())["output"])
            self.assertEqual([t["name"] for t in tools], ["keep"])
            blocked = asyncio.run(agent_tools._mcp_call_tool(sid, "drop", {}))
            self.assertTrue(blocked["error"])
        finally:
            mcp_registry.sessions.pop(sid, None)
            mcp_registry.tools.pop(sid, None)


class McpRemoteSessionLifetimeTest(ApiTest):
    def tearDown(self):
        import asyncio

        for sid in list(mcp._sessions):
            asyncio.run(mcp._disconnect(sid))
        super().tearDown()

    def test_sse_transport_stack_stays_open_until_disconnect(self):
        import asyncio
        import sys
        import types

        flags = {"transport_closed": False, "session_closed": False}

        class FakeTool:
            name = "ping"
            description = "ping tool"
            inputSchema = {"type": "object"}

        class FakeSession:
            def __init__(self, read, write):
                self.read = read
                self.write = write

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                flags["session_closed"] = True

            async def initialize(self):
                return None

            async def list_tools(self):
                return types.SimpleNamespace(tools=[FakeTool()])

        class FakeSseClient:
            async def __aenter__(self):
                return "read", "write"

            async def __aexit__(self, *exc):
                flags["transport_closed"] = True

        mcp_mod = types.ModuleType("mcp")
        mcp_mod.ClientSession = FakeSession
        client_pkg = types.ModuleType("mcp.client")
        sse_mod = types.ModuleType("mcp.client.sse")
        seen = {}

        def fake_sse(url, headers=None):
            seen["url"] = url
            seen["headers"] = headers
            return FakeSseClient()

        sse_mod.sse_client = fake_sse

        old = {name: sys.modules.get(name) for name in ("mcp", "mcp.client", "mcp.client.sse")}
        sys.modules["mcp"] = mcp_mod
        sys.modules["mcp.client"] = client_pkg
        sys.modules["mcp.client.sse"] = sse_mod
        self.addCleanup(lambda: _restore_modules(old))

        db = self.db()
        srv = McpServer(
            name="remote",
            transport="sse",
            url="http://example.test/mcp",
            headers='{"Authorization":"Bearer private"}',
        )
        db.add(srv)
        db.commit()
        sid = srv.id

        ok, err = asyncio.run(mcp._connect(sid, db))
        self.assertTrue(ok, err)
        self.assertIn(sid, mcp._sessions)
        self.assertIn(sid, mcp._stacks)
        self.assertEqual(mcp._tools[sid][0]["name"], "ping")
        self.assertFalse(flags["transport_closed"])
        self.assertEqual(seen["headers"], {"Authorization": "Bearer private"})

        asyncio.run(mcp._disconnect(sid))
        self.assertTrue(flags["transport_closed"])
        self.assertTrue(flags["session_closed"])
        db.close()


def _restore_modules(old):
    import sys

    for name, mod in old.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod

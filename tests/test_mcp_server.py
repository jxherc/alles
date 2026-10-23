"""stage 3d - alles as an MCP server (JSON-RPC over the registry). tests first (RED)."""

import asyncio
import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import mcp_server
from services.delegated_actions import create_grant
from tests._client import ApiTest


def _h(req):
    return asyncio.run(mcp_server.handle(req))


class HandlerTests(ApiTest):
    def _grant(self, name):
        db = self.db()
        create_grant(
            db,
            scope_kind="general",
            scope_id="",
            capability=f"tool:{name}",
            access_mode="manage" if name in {"shell", "write_file"} else "read",
        )
        db.commit()
        db.close()

    def test_initialize(self):
        r = _h({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(r["id"], 1)
        self.assertIn("protocolVersion", r["result"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "alles")

    def test_tools_list_carries_registry(self):
        self._grant("shell")
        r = _h({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in r["result"]["tools"]}
        self.assertIn("shell", names)
        shell = next(t for t in r["result"]["tools"] if t["name"] == "shell")
        self.assertIn("inputSchema", shell)
        self.assertIn("command", shell["inputSchema"].get("properties", {}))

    def test_tools_call_invokes(self):
        from services import capabilities

        self._grant("recall")

        async def fake(name, args, kind="tool"):
            return {"echoed": name, "args": args}

        orig = capabilities.invoke
        capabilities.invoke = fake
        try:
            r = _h(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"query": "hi"}},
                }
            )
        finally:
            capabilities.invoke = orig
        self.assertFalse(r["result"].get("isError"))
        self.assertIn("recall", r["result"]["content"][0]["text"])

    def test_tools_call_error_marks_iserror(self):
        from services import capabilities

        async def fake(name, args, kind="tool"):
            return {"error": "boom"}

        orig = capabilities.invoke
        capabilities.invoke = fake
        try:
            r = _h(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "x", "arguments": {}},
                }
            )
        finally:
            capabilities.invoke = orig
        self.assertTrue(r["result"]["isError"])

    def test_unknown_method(self):
        r = _h({"jsonrpc": "2.0", "id": 5, "method": "bogus/method"})
        self.assertEqual(r["error"]["code"], -32601)

    def test_ping(self):
        r = _h({"jsonrpc": "2.0", "id": 6, "method": "ping"})
        self.assertEqual(r["result"], {})

    def test_notification_returns_none(self):
        r = _h({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(r)

    def test_id_echoed(self):
        r = _h({"jsonrpc": "2.0", "id": "abc", "method": "ping"})
        self.assertEqual(r["id"], "abc")

    def test_call_unknown_tool_surfaces_error(self):
        r = _h(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "no_such_tool_xyz", "arguments": {}},
            }
        )
        # either a JSON-RPC error or an isError result is acceptable; must not raise
        self.assertTrue("error" in r or r["result"].get("isError"))

    def test_capabilities_bootstrap_once_for_repeated_rpc(self):
        from services import capabilities

        self._grant("recall")

        calls = []
        orig_bootstrap = capabilities.bootstrap
        orig_invoke = capabilities.invoke
        orig_bootstrapped = mcp_server._BOOTSTRAPPED

        def counted_bootstrap():
            calls.append("bootstrap")
            return orig_bootstrap()

        async def fake_invoke(name, args, kind="tool"):
            return {"name": name, "args": args}

        capabilities.clear()
        mcp_server._BOOTSTRAPPED = False
        capabilities.bootstrap = counted_bootstrap
        capabilities.invoke = fake_invoke
        try:
            _h({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
            _h(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"query": "hi"}},
                }
            )
        finally:
            capabilities.bootstrap = orig_bootstrap
            capabilities.invoke = orig_invoke
            mcp_server._BOOTSTRAPPED = orig_bootstrapped
        self.assertEqual(calls, ["bootstrap"])


class EndpointTests(ApiTest):
    def test_rpc_endpoint_roundtrip(self):
        r = self.client.post(
            "/api/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("tools", r.json()["result"])

    def test_rpc_notification_204(self):
        r = self.client.post(
            "/api/mcp/rpc", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self.assertEqual(r.status_code, 204)


if __name__ == "__main__":
    unittest.main()

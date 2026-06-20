from unittest import mock

from core.database import McpServer, Persona
from services import share
from tests._client import ApiTest


async def _fake_connect(server_id, db):
    return (False, "stubbed — not connecting in tests")


class PersonaShareTests(ApiTest):
    def _persona(self, name="Helper", prompt="You are a helpful research assistant."):
        d = self.db()
        p = Persona(name=name, system_prompt=prompt, emoji="🔬")
        d.add(p)
        d.commit()
        d.refresh(p)
        pid = p.id
        d.close()
        return pid

    def test_mint_persona_kind(self):
        pid = self._persona()
        d = self.db()
        sh = share.mint(d, "persona", pid)
        self.assertTrue(sh.token)
        self.assertEqual(share.lookup(d, sh.token).ref, pid)
        d.close()

    def test_share_endpoint_mints(self):
        pid = self._persona()
        r = self.client.post(f"/api/personas/{pid}/share").json()
        self.assertTrue(r["token"])
        d = self.db()
        self.assertIsNotNone(share.token_for(d, "persona", pid))
        d.close()

    def test_view_persona_bundle_html(self):
        pid = self._persona(name="Sherlock", prompt="Deduce relentlessly.")
        tok = self.client.post(f"/api/personas/{pid}/share").json()["token"]
        html = self.client.get(f"/s/{tok}").text
        self.assertIn("Sherlock", html)
        self.assertIn("Deduce relentlessly", html)

    def test_revoked_persona_404(self):
        pid = self._persona()
        tok = self.client.post(f"/api/personas/{pid}/share").json()["token"]
        self.client.delete(f"/api/personas/{pid}/share")
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_share_persona_unknown_404(self):
        self.assertEqual(self.client.post("/api/personas/ghost/share").status_code, 404)


class McpPresetTests(ApiTest):
    def test_presets_nonempty(self):
        presets = self.client.get("/api/mcp/presets").json()
        self.assertTrue(len(presets) >= 3)

    def test_preset_schema(self):
        for p in self.client.get("/api/mcp/presets").json():
            for k in ("id", "name", "transport", "command", "description"):
                self.assertIn(k, p)

    def test_add_preset_creates_server(self):
        with mock.patch("routes.mcp._connect", _fake_connect):
            pid = self.client.get("/api/mcp/presets").json()[0]["id"]
            r = self.client.post(f"/api/mcp/presets/{pid}")
        self.assertEqual(r.status_code, 200)
        d = self.db()
        self.assertGreaterEqual(d.query(McpServer).count(), 1)
        d.close()

    def test_add_preset_unknown_404(self):
        with mock.patch("routes.mcp._connect", _fake_connect):
            self.assertEqual(self.client.post("/api/mcp/presets/nope").status_code, 404)

    def test_add_preset_interpolates_params(self):
        with mock.patch("routes.mcp._connect", _fake_connect):
            # a preset with a {db_path}-style placeholder gets it filled from params
            r = self.client.post(
                "/api/mcp/presets/sqlite", json={"params": {"db_path": "/tmp/my.db"}}
            )
        self.assertEqual(r.status_code, 200)
        d = self.db()
        srv = d.query(McpServer).order_by(McpServer.created_at.desc()).first()
        self.assertIn("/tmp/my.db", srv.args)
        d.close()

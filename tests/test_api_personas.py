import json
from tests._client import ApiTest


class PersonasApiTest(ApiTest):
    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/personas").json(), [])

    def test_create_and_default_is_exclusive(self):
        a = self.client.post("/api/personas", json={"name": "a", "is_default": True}).json()
        self.assertTrue(a["is_default"])
        # second default should knock the first one off
        self.client.post("/api/personas", json={"name": "b", "is_default": True})
        defaults = [p["name"] for p in self.client.get("/api/personas").json() if p["is_default"]]
        self.assertEqual(defaults, ["b"])

    def test_patch_and_delete(self):
        pid = self.client.post("/api/personas", json={"name": "p", "emoji": "🤖"}).json()["id"]
        r = self.client.patch(f"/api/personas/{pid}", json={"name": "p2", "system_prompt": "be terse"})
        self.assertEqual(r.json()["name"], "p2")
        self.assertEqual(r.json()["system_prompt"], "be terse")
        self.assertEqual(self.client.delete(f"/api/personas/{pid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/personas").json(), [])

    def test_missing_404(self):
        self.assertEqual(self.client.patch("/api/personas/nope", json={"name": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/personas/nope").status_code, 404)

    def test_partial_patch_keeps_other_fields(self):
        # editing just the prompt must NOT wipe model / default — the old PersonaBody patch did
        pid = self.client.post("/api/personas", json={
            "name": "coder", "model": "gpt-x", "is_default": True}).json()["id"]
        r = self.client.patch(f"/api/personas/{pid}", json={"system_prompt": "be terse"}).json()
        self.assertEqual(r["system_prompt"], "be terse")
        self.assertEqual(r["model"], "gpt-x")     # untouched
        self.assertTrue(r["is_default"])          # untouched

    def test_temperature_roundtrip(self):
        pid = self.client.post("/api/personas", json={"name": "loose", "temperature": 1.3}).json()["id"]
        self.assertEqual(self.client.get("/api/personas").json()[0]["temperature"], 1.3)
        # clearing it sets null, doesn't error
        r = self.client.patch(f"/api/personas/{pid}", json={"temperature": None}).json()
        self.assertIsNone(r["temperature"])
        # default (unset) persona has null temperature
        pid2 = self.client.post("/api/personas", json={"name": "plain"}).json()["id"]
        self.assertIsNone([p for p in self.client.get("/api/personas").json() if p["id"] == pid2][0]["temperature"])

    def test_default_mode_roundtrip(self):
        pid = self.client.post("/api/personas", json={"name": "ag", "default_mode": "agent"}).json()["id"]
        self.assertEqual(self.client.get("/api/personas").json()[0]["default_mode"], "agent")
        r = self.client.patch(f"/api/personas/{pid}", json={"default_mode": "chat"}).json()
        self.assertEqual(r["default_mode"], "chat")

    def test_decide_mode(self):
        from routes.chat import _decide_mode
        plain = "tell me a joke"
        doish = "what's on my calendar today"
        # agent persona always runs tools (and gates on approval)
        self.assertEqual(_decide_mode("chat", "agent", plain, False, True), ("agent", True))
        # chat-only persona never auto-promotes, even on a do-something message
        self.assertEqual(_decide_mode("chat", "chat", doish, False, True), ("chat", False))
        # no persona default → intent-based: plain stays chat, do-ish promotes
        self.assertEqual(_decide_mode("chat", "", plain, False, True), ("chat", False))
        self.assertEqual(_decide_mode("chat", "", doish, False, True)[0], "agent")
        # explicit agent turn or simple-chat short-circuit
        self.assertEqual(_decide_mode("agent", "chat", plain, False, True), ("agent", False))
        self.assertEqual(_decide_mode("chat", "agent", plain, True, True), ("chat", False))

    def test_accent_roundtrip(self):
        pid = self.client.post("/api/personas", json={"name": "amber", "accent": "#fbbf24"}).json()["id"]
        self.assertEqual(self.client.get("/api/personas").json()[0]["accent"], "#fbbf24")
        r = self.client.patch(f"/api/personas/{pid}", json={"accent": ""}).json()
        self.assertEqual(r["accent"], "")

    def test_duplicate(self):
        pid = self.client.post("/api/personas", json={
            "name": "orig", "emoji": "🤖", "system_prompt": "be terse", "model": "m1",
            "accent": "#60a5fa", "default_mode": "agent"}).json()["id"]
        dup = self.client.post(f"/api/personas/{pid}/duplicate").json()
        self.assertEqual(dup["name"], "orig copy")
        self.assertEqual(dup["system_prompt"], "be terse")
        self.assertEqual(dup["model"], "m1")
        self.assertEqual(dup["accent"], "#60a5fa")
        self.assertEqual(dup["default_mode"], "agent")
        self.assertFalse(dup["is_default"])
        self.assertNotEqual(dup["id"], pid)
        self.assertEqual(self.client.post("/api/personas/nope/duplicate").status_code, 404)

    def test_seed_default_personas(self):
        import tempfile, os
        from pathlib import Path
        from routes import personas as pmod
        orig = pmod._SEED_SENTINEL
        tmp = Path(tempfile.gettempdir()) / f"_pseed_{os.getpid()}_{id(self)}"
        if tmp.exists(): tmp.unlink()
        pmod._SEED_SENTINEL = tmp
        try:
            n = pmod.seed_default_personas()
            self.assertEqual(n, len(pmod._STARTERS))
            rows = self.client.get("/api/personas").json()
            self.assertIn("coder", [p["name"] for p in rows])
            self.assertEqual(len([p for p in rows if p["is_default"]]), 1)
            self.assertEqual(pmod.seed_default_personas(), 0)   # sentinel → no-op
        finally:
            pmod._SEED_SENTINEL = orig
            if tmp.exists(): tmp.unlink()

    def test_persona_pins_model_and_switches_endpoint(self):
        from routes.chat import _apply_persona_model
        from core.database import ModelEndpoint, Session, Persona
        db = self.db()
        ep1 = ModelEndpoint(name="e1", base_url="http://x", api_key="", enabled=True, cached_models=json.dumps(["m1"]))
        ep2 = ModelEndpoint(name="e2", base_url="http://y", api_key="", enabled=True, cached_models=json.dumps(["m2"]))
        db.add_all([ep1, ep2]); db.commit()
        p = Persona(name="coder", model="m2"); db.add(p); db.commit()
        s = Session(name="t", persona_id=p.id, endpoint_id=ep1.id); db.add(s); db.commit()
        new_ep, model = _apply_persona_model(s, ep1, "m1", db)
        self.assertEqual(model, "m2")
        self.assertEqual(new_ep.id, ep2.id)   # hopped to the endpoint that serves m2
        # persona with no pinned model leaves things alone
        s.persona_id = None; db.commit()
        same_ep, same_model = _apply_persona_model(s, ep1, "m1", db)
        self.assertEqual((same_ep.id, same_model), (ep1.id, "m1"))
        db.close()

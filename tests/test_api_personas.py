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

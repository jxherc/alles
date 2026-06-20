import json

from tests._client import ApiTest
from core.database import ModelEndpoint


class SetupStatusApiTest(ApiTest):
    def test_unconfigured_on_fresh_install(self):
        st = self.client.get("/api/setup/status").json()
        self.assertFalse(st["configured"])
        self.assertEqual(st["endpoints"], 0)

    def test_endpoint_without_models_is_not_configured(self):
        d = self.db()
        d.add(ModelEndpoint(name="Empty", base_url="http://x", cached_models="[]"))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 1)
        self.assertFalse(st["configured"])  # enabled but no usable models yet
        self.assertEqual(st["endpoints_with_models"], 0)

    def test_configured_once_an_endpoint_has_models(self):
        d = self.db()
        d.add(
            ModelEndpoint(name="DeepSeek", base_url="http://x", cached_models=json.dumps(["chat"]))
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertTrue(st["configured"])
        self.assertEqual(st["endpoints_with_models"], 1)

    def test_disabled_endpoint_does_not_count(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="Off", base_url="http://x", cached_models=json.dumps(["m"]), enabled=False
            )
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 0)  # only enabled endpoints are counted
        self.assertFalse(st["configured"])

    def test_multiple_endpoints_counted(self):
        d = self.db()
        d.add(ModelEndpoint(name="A", base_url="http://a", cached_models=json.dumps(["m1"])))
        d.add(ModelEndpoint(name="B", base_url="http://b", cached_models=json.dumps(["m2"])))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 2)
        self.assertEqual(st["endpoints_with_models"], 2)
        self.assertTrue(st["configured"])

    def test_mixed_enabled_disabled(self):
        d = self.db()
        d.add(ModelEndpoint(name="On", base_url="http://on", cached_models=json.dumps(["x"])))
        d.add(
            ModelEndpoint(
                name="Off", base_url="http://off", cached_models=json.dumps(["y"]), enabled=False
            )
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 1)
        self.assertEqual(st["endpoints_with_models"], 1)
        self.assertTrue(st["configured"])

    def test_add_endpoint_appears_in_models_list(self):
        r = self.client.post(
            "/api/models/endpoint",
            json={"name": "Local", "base_url": "http://localhost:11434", "api_key": ""},
        )
        self.assertEqual(r.status_code, 200)
        ep = r.json()
        self.assertEqual(ep["name"], "Local")
        self.assertIn("id", ep)

    def test_delete_endpoint(self):
        r = self.client.post(
            "/api/models/endpoint",
            json={"name": "Temp", "base_url": "http://tmp", "api_key": ""},
        )
        eid = r.json()["id"]
        # should appear in list
        eps = self.client.get("/api/models").json()
        ids = [e["id"] for e in eps]
        self.assertIn(eid, ids)
        # delete
        dr = self.client.delete(f"/api/models/endpoint/{eid}")
        self.assertEqual(dr.status_code, 200)
        self.assertTrue(dr.json()["ok"])
        # gone
        eps2 = self.client.get("/api/models").json()
        self.assertNotIn(eid, [e["id"] for e in eps2])

    def test_endpoints_with_models_zero_when_none_have_models(self):
        d = self.db()
        d.add(ModelEndpoint(name="Empty1", base_url="http://e1", cached_models="[]"))
        d.add(ModelEndpoint(name="Empty2", base_url="http://e2", cached_models="[]"))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 2)
        self.assertEqual(st["endpoints_with_models"], 0)
        self.assertFalse(st["configured"])

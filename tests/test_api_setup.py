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
        d.commit(); d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 1)
        self.assertFalse(st["configured"])          # enabled but no usable models yet
        self.assertEqual(st["endpoints_with_models"], 0)

    def test_configured_once_an_endpoint_has_models(self):
        d = self.db()
        d.add(ModelEndpoint(name="DeepSeek", base_url="http://x", cached_models=json.dumps(["chat"])))
        d.commit(); d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertTrue(st["configured"])
        self.assertEqual(st["endpoints_with_models"], 1)

    def test_disabled_endpoint_does_not_count(self):
        d = self.db()
        d.add(ModelEndpoint(name="Off", base_url="http://x", cached_models=json.dumps(["m"]), enabled=False))
        d.commit(); d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 0)        # only enabled endpoints are counted
        self.assertFalse(st["configured"])

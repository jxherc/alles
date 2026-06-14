import json

from tests._client import ApiTest
from core.database import ModelEndpoint


class CompareApiTest(ApiTest):
    def _endpoint(self):
        d = self.db()
        ep = ModelEndpoint(name="Test", base_url="http://localhost", cached_models=json.dumps(["m1"]))
        d.add(ep); d.commit(); eid = ep.id; d.close()
        return eid

    def test_empty_models_400(self):
        self.assertEqual(self.client.post("/api/compare", json={"message": "hi", "models": []}).status_code, 400)

    def test_bogus_endpoint_skipped(self):
        r = self.client.post("/api/compare", json={"message": "hi", "models": [{"endpoint_id": "nope", "model": "x"}]})
        self.assertEqual(r.json()["count"], 0)   # unresolved endpoints are dropped

    def test_real_endpoint_counted_then_stoppable(self):
        eid = self._endpoint()
        r = self.client.post("/api/compare", json={"message": "hi", "models": [{"endpoint_id": eid, "model": "m1"}]}).json()
        self.assertEqual(r["count"], 1)
        self.assertEqual(self.client.delete(f"/api/compare/{r['compare_id']}").json(), {"ok": True})

    def test_stream_bad_id_404(self):
        self.assertEqual(self.client.get("/api/compare/nope/stream/0").status_code, 404)

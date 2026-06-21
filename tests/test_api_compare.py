import json

from core.database import ModelEndpoint
from tests._client import ApiTest


class CompareApiTest(ApiTest):
    def _endpoint(self):
        d = self.db()
        ep = ModelEndpoint(
            name="Test", base_url="http://localhost", cached_models=json.dumps(["m1"])
        )
        d.add(ep)
        d.commit()
        eid = ep.id
        d.close()
        return eid

    def test_empty_models_400(self):
        self.assertEqual(
            self.client.post("/api/compare", json={"message": "hi", "models": []}).status_code, 400
        )

    def test_bogus_endpoint_skipped(self):
        r = self.client.post(
            "/api/compare",
            json={"message": "hi", "models": [{"endpoint_id": "nope", "model": "x"}]},
        )
        self.assertEqual(r.json()["count"], 0)  # unresolved endpoints are dropped

    def test_real_endpoint_counted_then_stoppable(self):
        eid = self._endpoint()
        r = self.client.post(
            "/api/compare", json={"message": "hi", "models": [{"endpoint_id": eid, "model": "m1"}]}
        ).json()
        self.assertEqual(r["count"], 1)
        self.assertEqual(self.client.delete(f"/api/compare/{r['compare_id']}").json(), {"ok": True})

    def test_stream_bad_id_404(self):
        self.assertEqual(self.client.get("/api/compare/nope/stream/0").status_code, 404)

    def test_delete_missing_id_ok(self):
        # deleting a non-existent compare_id should still return ok (idempotent)
        r = self.client.delete("/api/compare/no-such-id")
        self.assertEqual(r.json(), {"ok": True})

    def test_stream_bad_index_404(self):
        eid = self._endpoint()
        r = self.client.post(
            "/api/compare",
            json={"message": "hi", "models": [{"endpoint_id": eid, "model": "m1"}]},
        ).json()
        cid = r["compare_id"]
        # slot 99 doesn't exist
        self.assertEqual(self.client.get(f"/api/compare/{cid}/stream/99").status_code, 404)

    def test_two_endpoints_both_counted(self):
        d = self.db()
        ep1 = ModelEndpoint(name="E1", base_url="http://a", cached_models=json.dumps(["ma"]))
        ep2 = ModelEndpoint(name="E2", base_url="http://b", cached_models=json.dumps(["mb"]))
        d.add_all([ep1, ep2])
        d.commit()
        eid1, eid2 = ep1.id, ep2.id
        d.close()
        r = self.client.post(
            "/api/compare",
            json={
                "message": "compare",
                "models": [
                    {"endpoint_id": eid1, "model": "ma"},
                    {"endpoint_id": eid2, "model": "mb"},
                ],
            },
        ).json()
        self.assertEqual(r["count"], 2)

    def test_compare_id_is_uuid_string(self):
        eid = self._endpoint()
        r = self.client.post(
            "/api/compare",
            json={"message": "hi", "models": [{"endpoint_id": eid, "model": "m1"}]},
        ).json()
        import uuid

        # should parse as a valid UUID
        uuid.UUID(r["compare_id"])  # raises ValueError if not valid

    def test_mixed_valid_and_invalid_endpoints(self):
        eid = self._endpoint()
        r = self.client.post(
            "/api/compare",
            json={
                "message": "hi",
                "models": [
                    {"endpoint_id": eid, "model": "m1"},
                    {"endpoint_id": "bogus", "model": "x"},
                ],
            },
        ).json()
        # only the real one makes it in
        self.assertEqual(r["count"], 1)

    # ── blind-vote leaderboard ──
    def test_vote_requires_winner(self):
        self.assertEqual(self.client.post("/api/compare/vote", json={"winner": " "}).status_code, 400)

    def test_vote_and_stats_winrate(self):
        self.client.post("/api/compare/vote", json={"winner": "gpt", "loser": "claude"})
        self.client.post("/api/compare/vote", json={"winner": "gpt", "loser": "claude"})
        self.client.post("/api/compare/vote", json={"winner": "claude", "loser": "gpt"})
        stats = self.client.get("/api/compare/stats").json()
        self.assertEqual(stats["votes"], 3)
        by = {m["model"]: m for m in stats["models"]}
        self.assertEqual((by["gpt"]["wins"], by["gpt"]["losses"]), (2, 1))
        self.assertEqual(by["gpt"]["win_rate"], round(2 / 3, 3))
        self.assertEqual(stats["models"][0]["model"], "gpt")  # most wins first

    def test_stats_empty(self):
        self.assertEqual(self.client.get("/api/compare/stats").json(), {"votes": 0, "models": []})

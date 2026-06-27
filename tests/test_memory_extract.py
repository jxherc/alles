"""POST /api/memories/extract — guard that max_memories caps correctly (a negative value used to
slice off the newest line via lines[:-1] instead of returning nothing)."""

import json
from unittest import mock

from core.database import Message, ModelEndpoint, Session
from tests._client import ApiTest


async def _fake_complete(messages, base, key, model, max_tokens=512):
    return "- likes coffee\n- runs in the morning\n- lives in berlin"


class MemoryExtractTests(ApiTest):
    def _seed(self):
        d = self.db()
        ep = ModelEndpoint(name="e", base_url="http://x", api_key="k",
                           enabled=True, cached_models=json.dumps(["m1"]))
        d.add(ep)
        d.flush()
        s = Session(name="c", model="m1", endpoint_id=ep.id)
        d.add(s)
        d.flush()
        d.add(Message(session_id=s.id, role="user", content="I like coffee and run mornings in Berlin"))
        d.commit()
        sid = s.id
        d.close()
        return sid

    def test_negative_max_extracts_nothing(self):
        sid = self._seed()
        with mock.patch("services.llm.simple_complete", _fake_complete):
            r = self.client.post("/api/memories/extract", json={"session_id": sid, "max_memories": -1})
        self.assertEqual(r.status_code, 200)
        # 3 lines came back; -1 must not mean "all but the last" — it caps to 0
        self.assertEqual(r.json()["extracted"], 0)

    def test_positive_max_caps(self):
        sid = self._seed()
        with mock.patch("services.llm.simple_complete", _fake_complete):
            r = self.client.post("/api/memories/extract", json={"session_id": sid, "max_memories": 2})
        self.assertEqual(r.json()["extracted"], 2)

import json

from tests._client import ApiTest
from core.database import Session, Message


class UsageApiTest(ApiTest):
    def _seed(self):
        d = self.db()
        s = Session(name="costly chat", model="deepseek-v4-pro")
        d.add(s); d.commit(); sid = s.id
        d.add(Message(session_id=sid, role="user", content="hi"))
        d.add(Message(session_id=sid, role="assistant", content="hello",
                      meta=json.dumps({"model": "deepseek-v4-pro",
                                       "usage": {"prompt_tokens": 100, "completion_tokens": 40}})))
        d.add(Message(session_id=sid, role="assistant", content="more",
                      meta=json.dumps({"model": "deepseek-v4-pro",
                                       "usage": {"prompt_tokens": 50, "completion_tokens": 10}})))
        d.commit(); d.close()
        return sid

    def test_summary_aggregates(self):
        self._seed()
        s = self.client.get("/api/usage/summary").json()
        self.assertEqual(s["total_prompt"], 150)
        self.assertEqual(s["total_completion"], 50)
        self.assertEqual(s["total_tokens"], 200)
        self.assertEqual(s["total_messages"], 2)
        self.assertEqual(s["by_model"][0]["name"], "deepseek-v4-pro")

    def test_by_session(self):
        sid = self._seed()
        r = self.client.get("/api/usage/by-session").json()
        self.assertEqual(len(r["sessions"]), 1)
        row = r["sessions"][0]
        self.assertEqual(row["session_id"], sid)
        self.assertEqual(row["name"], "costly chat")
        self.assertEqual(row["total"], 200)
        self.assertEqual(row["messages"], 2)

    def test_empty_is_zeroed(self):
        s = self.client.get("/api/usage/summary").json()
        self.assertEqual(s["total_tokens"], 0)
        self.assertEqual(self.client.get("/api/usage/by-session").json()["sessions"], [])

import json

from core.database import Message, Session
from tests._client import ApiTest


class UsageApiTest(ApiTest):
    def _seed(self):
        d = self.db()
        s = Session(name="costly chat", model="deepseek-v4-pro")
        d.add(s)
        d.commit()
        sid = s.id
        d.add(Message(session_id=sid, role="user", content="hi"))
        d.add(
            Message(
                session_id=sid,
                role="assistant",
                content="hello",
                meta=json.dumps(
                    {
                        "model": "deepseek-v4-pro",
                        "usage": {"prompt_tokens": 100, "completion_tokens": 40},
                    }
                ),
            )
        )
        d.add(
            Message(
                session_id=sid,
                role="assistant",
                content="more",
                meta=json.dumps(
                    {
                        "model": "deepseek-v4-pro",
                        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
                    }
                ),
            )
        )
        d.commit()
        d.close()
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

    def test_messages_without_usage_ignored(self):
        # user messages + assistant messages with no meta shouldn't blow up
        d = self.db()
        s = Session(name="plain chat", model="gpt-4o")
        d.add(s)
        d.commit()
        d.add(Message(session_id=s.id, role="user", content="hey"))
        d.add(Message(session_id=s.id, role="assistant", content="yo", meta=None))
        d.commit()
        d.close()
        r = self.client.get("/api/usage/summary").json()
        self.assertEqual(r["total_tokens"], 0)

    def test_summary_by_model_sorted_descending(self):
        d = self.db()
        s1 = Session(name="s1", model="cheap")
        s2 = Session(name="s2", model="expensive")
        d.add_all([s1, s2])
        d.commit()
        d.add(
            Message(
                session_id=s1.id,
                role="assistant",
                content="a",
                meta=json.dumps(
                    {"model": "cheap", "usage": {"prompt_tokens": 5, "completion_tokens": 5}}
                ),
            )
        )
        d.add(
            Message(
                session_id=s2.id,
                role="assistant",
                content="b",
                meta=json.dumps(
                    {
                        "model": "expensive",
                        "usage": {"prompt_tokens": 500, "completion_tokens": 500},
                    }
                ),
            )
        )
        d.commit()
        d.close()
        models = self.client.get("/api/usage/summary").json()["by_model"]
        self.assertEqual(models[0]["name"], "expensive")
        self.assertEqual(models[0]["total"], 1000)

    def test_anthropic_token_field_names(self):
        # anthropic uses input_tokens/output_tokens instead of prompt/completion
        d = self.db()
        s = Session(name="claude chat", model="claude-3-5-sonnet")
        d.add(s)
        d.commit()
        d.add(
            Message(
                session_id=s.id,
                role="assistant",
                content="hi",
                meta=json.dumps(
                    {
                        "model": "claude-3-5-sonnet",
                        "usage": {"input_tokens": 200, "output_tokens": 80},
                    }
                ),
            )
        )
        d.commit()
        d.close()
        r = self.client.get("/api/usage/summary").json()
        self.assertEqual(r["total_prompt"], 200)
        self.assertEqual(r["total_completion"], 80)

    def test_by_session_limit_param(self):
        d = self.db()
        for i in range(3):
            s = Session(name=f"s{i}", model="m")
            d.add(s)
            d.commit()
            d.add(
                Message(
                    session_id=s.id,
                    role="assistant",
                    content="x",
                    meta=json.dumps(
                        {
                            "model": "m",
                            "usage": {"prompt_tokens": (i + 1) * 10, "completion_tokens": 0},
                        }
                    ),
                )
            )
            d.commit()
        d.close()
        r = self.client.get("/api/usage/by-session?limit=2").json()
        self.assertEqual(len(r["sessions"]), 2)

    def test_by_session_sorted_by_total_desc(self):
        d = self.db()
        cheap = Session(name="cheap", model="m")
        pricey = Session(name="pricey", model="m")
        d.add_all([cheap, pricey])
        d.commit()
        d.add(
            Message(
                session_id=cheap.id,
                role="assistant",
                content="a",
                meta=json.dumps(
                    {"model": "m", "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
                ),
            )
        )
        d.add(
            Message(
                session_id=pricey.id,
                role="assistant",
                content="b",
                meta=json.dumps(
                    {"model": "m", "usage": {"prompt_tokens": 999, "completion_tokens": 0}}
                ),
            )
        )
        d.commit()
        d.close()
        rows = self.client.get("/api/usage/by-session").json()["sessions"]
        self.assertEqual(rows[0]["name"], "pricey")

    def test_summary_has_by_month_key(self):
        # even empty, by_month should be present and be a list
        r = self.client.get("/api/usage/summary").json()
        self.assertIn("by_month", r)
        self.assertIsInstance(r["by_month"], list)

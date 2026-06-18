import json
import unittest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Message
from routes import usage as U


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    Message.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _msg(db, role, meta, ts):
    db.add(Message(session_id="s1", role=role, content="x", meta=json.dumps(meta), timestamp=ts))
    db.commit()


class UsageTests(unittest.TestCase):
    def test_aggregation(self):
        db = _mkdb()
        _msg(
            db,
            "assistant",
            {"usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "claude-opus-4-8"},
            datetime(2026, 6, 14),
        )
        _msg(
            db,
            "assistant",
            {"usage": {"prompt_tokens": 200, "completion_tokens": 80}, "model": "claude-opus-4-8"},
            datetime(2026, 6, 20),
        )
        _msg(
            db,
            "assistant",
            {"usage": {"input_tokens": 10, "output_tokens": 5}, "model": "deepseek-v4"},
            datetime(2026, 5, 1),
        )  # anthropic-style keys
        _msg(db, "user", {}, datetime(2026, 6, 14))  # ignored (not assistant)
        _msg(db, "assistant", {"model": "x"}, datetime(2026, 6, 14))  # ignored (no usage)

        s = U.usage_summary(db)
        self.assertEqual(s["total_prompt"], 310)
        self.assertEqual(s["total_completion"], 135)
        self.assertEqual(s["total_tokens"], 445)
        self.assertEqual(s["total_messages"], 3)

        models = {m["name"]: m["total"] for m in s["by_model"]}
        self.assertEqual(models["claude-opus-4-8"], 430)
        self.assertEqual(models["deepseek-v4"], 15)
        self.assertEqual(s["by_model"][0]["name"], "claude-opus-4-8")  # biggest first

        months = {m["name"]: m["total"] for m in s["by_month"]}
        self.assertEqual(months["2026-06"], 430)
        self.assertEqual(months["2026-05"], 15)

    def test_empty(self):
        s = U.usage_summary(_mkdb())
        self.assertEqual(s["total_tokens"], 0)
        self.assertEqual(s["total_messages"], 0)


if __name__ == "__main__":
    unittest.main()

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


class ToksTests(unittest.TestCase):
    def test_none_returns_zeros(self):
        self.assertEqual(U._toks(None), (0, 0))

    def test_non_dict_string_returns_zeros(self):
        self.assertEqual(U._toks("prompt_tokens: 5"), (0, 0))

    def test_non_castable_string_values_return_zeros(self):
        self.assertEqual(U._toks({"prompt_tokens": "abc", "completion_tokens": "xyz"}), (0, 0))

    def test_only_prompt_tokens(self):
        self.assertEqual(U._toks({"prompt_tokens": 42}), (42, 0))

    def test_only_output_tokens_anthropic_style(self):
        self.assertEqual(U._toks({"input_tokens": 10, "output_tokens": 5}), (10, 5))

    def test_integer_values(self):
        self.assertEqual(U._toks({"prompt_tokens": 100, "completion_tokens": 200}), (100, 200))

    def test_empty_dict_returns_zeros(self):
        self.assertEqual(U._toks({}), (0, 0))


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

    def test_by_month_sorted_ascending(self):
        db = _mkdb()
        _msg(db, "assistant", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "m"}, datetime(2026, 8, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 20, "completion_tokens": 3}, "model": "m"}, datetime(2026, 3, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 15, "completion_tokens": 2}, "model": "m"}, datetime(2026, 6, 15))
        s = U.usage_summary(db)
        names = [r["name"] for r in s["by_month"]]
        self.assertEqual(names, sorted(names))

    def test_by_model_sorted_descending_by_total(self):
        db = _mkdb()
        _msg(db, "assistant", {"usage": {"prompt_tokens": 5, "completion_tokens": 5}, "model": "small"}, datetime(2026, 6, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 500, "completion_tokens": 500}, "model": "big"}, datetime(2026, 6, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 50, "completion_tokens": 50}, "model": "mid"}, datetime(2026, 6, 1))
        s = U.usage_summary(db)
        totals = [r["total"] for r in s["by_model"]]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(s["by_model"][0]["name"], "big")

    def test_zero_usage_message_not_counted(self):
        # a message with usage dict that has all zeros → skipped (p==0 and c==0)
        db = _mkdb()
        _msg(db, "assistant", {"usage": {"prompt_tokens": 0, "completion_tokens": 0}, "model": "m"}, datetime(2026, 6, 1))
        s = U.usage_summary(db)
        self.assertEqual(s["total_messages"], 0)

    def test_by_model_messages_count(self):
        db = _mkdb()
        _msg(db, "assistant", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "gpt-x"}, datetime(2026, 6, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 20, "completion_tokens": 8}, "model": "gpt-x"}, datetime(2026, 6, 2))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 30, "completion_tokens": 9}, "model": "gpt-x"}, datetime(2026, 6, 3))
        s = U.usage_summary(db)
        m = next(r for r in s["by_model"] if r["name"] == "gpt-x")
        self.assertEqual(m["messages"], 3)

    def test_invalid_json_meta_skipped(self):
        db = _mkdb()
        # raw insert with broken JSON
        db.execute(
            Message.__table__.insert(),
            {"session_id": "s1", "role": "assistant", "content": "x", "meta": "{not valid json", "timestamp": datetime(2026, 6, 1)}
        )
        db.commit()
        # should not raise, just skip the bad row
        s = U.usage_summary(db)
        self.assertEqual(s["total_messages"], 0)

    def test_response_has_all_keys(self):
        s = U.usage_summary(_mkdb())
        for key in ("total_prompt", "total_completion", "total_tokens", "total_messages", "by_month", "by_model"):
            self.assertIn(key, s)

    def test_multiple_models_separate_buckets(self):
        db = _mkdb()
        _msg(db, "assistant", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "a"}, datetime(2026, 6, 1))
        _msg(db, "assistant", {"usage": {"prompt_tokens": 20, "completion_tokens": 8}, "model": "b"}, datetime(2026, 6, 1))
        s = U.usage_summary(db)
        names = {r["name"] for r in s["by_model"]}
        self.assertIn("a", names)
        self.assertIn("b", names)
        self.assertEqual(len(s["by_model"]), 2)


if __name__ == "__main__":
    unittest.main()

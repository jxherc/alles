import unittest
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import JournalEntry
from routes import journal as J
from routes.journal import EntryBody


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    JournalEntry.__table__.create(eng)
    return sessionmaker(bind=eng)()


class StreakTests(unittest.TestCase):
    def test_consecutive(self):
        today = date(2026, 6, 14)
        ds = {(today - timedelta(days=i)).isoformat() for i in range(5)}
        self.assertEqual(J._streak(ds, today), 5)

    def test_gap_breaks(self):
        today = date(2026, 6, 14)
        ds = {today.isoformat(), (today - timedelta(days=2)).isoformat()}
        self.assertEqual(J._streak(ds, today), 1)

    def test_unwritten_today_doesnt_zero(self):
        today = date(2026, 6, 14)
        ds = {(today - timedelta(days=1)).isoformat(), (today - timedelta(days=2)).isoformat()}
        self.assertEqual(J._streak(ds, today), 2)

    def test_empty(self):
        self.assertEqual(J._streak(set(), date(2026, 6, 14)), 0)


class CrudTests(unittest.TestCase):
    def test_upsert_is_one_per_day(self):
        db = _mkdb()
        out = J.upsert_entry("2026-06-14", EntryBody(content="hello world", mood="🙂", tags="x"), db)
        self.assertEqual(out["words"], 2)
        self.assertEqual(out["mood"], "🙂")
        J.upsert_entry("2026-06-14", EntryBody(content="changed text here now"), db)
        got = J.get_entry("2026-06-14", db)
        self.assertTrue(got["exists"])
        self.assertEqual(got["content"], "changed text here now")
        self.assertEqual(J.list_entries("", 60, db)["stats"]["total"], 1)   # not duplicated

    def test_get_missing_returns_shell(self):
        got = J.get_entry("2026-01-01", _mkdb())
        self.assertFalse(got["exists"])
        self.assertEqual(got["content"], "")

    def test_delete(self):
        db = _mkdb()
        J.upsert_entry("2026-06-14", EntryBody(content="x"), db)
        J.delete_entry("2026-06-14", db)
        self.assertFalse(J.get_entry("2026-06-14", db)["exists"])

    def test_bad_date_rejected(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            J.get_entry("not-a-date", _mkdb())

    def test_prompt_is_question(self):
        self.assertIn("?", J.todays_prompt()["prompt"])


class DepthTests(unittest.TestCase):
    def test_search_export_calendar(self):
        db = _mkdb()
        J.upsert_entry("2026-06-14", EntryBody(content="found the needle today", mood="🙂"), db)
        J.upsert_entry("2026-06-13", EntryBody(content="ordinary day"), db)
        r = J.search_entries("needle", db)
        self.assertEqual(len(r["results"]), 1)
        self.assertEqual(r["results"][0]["date"], "2026-06-14")
        ex = J.export_entries(db)
        self.assertEqual(ex["count"], 2)
        self.assertIn("found the needle", ex["markdown"])
        cal = J.entry_calendar(2026, db)
        self.assertIn("2026-06-14", cal["days"])
        self.assertEqual(cal["days"]["2026-06-14"], 4)   # word count


if __name__ == "__main__":
    unittest.main()

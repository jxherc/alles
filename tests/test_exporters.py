"""stage 3h - multi-format export framework. tests first (RED)."""

import json
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import exporters as ex


class EncoderTests(unittest.TestCase):
    def test_csv_header_and_rows(self):
        out = ex.to_csv([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "a,b")
        self.assertEqual(lines[1], "1,2")

    def test_csv_union_of_keys(self):
        out = ex.to_csv([{"a": 1}, {"b": 2}])
        self.assertEqual(out.strip().splitlines()[0], "a,b")

    def test_csv_quotes_commas_and_quotes(self):
        out = ex.to_csv([{"x": 'he said "hi", ok'}])
        self.assertIn('"he said ""hi"", ok"', out)

    def test_csv_empty(self):
        self.assertEqual(ex.to_csv([]), "")

    def test_json_roundtrip(self):
        rows = [{"a": 1}, {"b": "two"}]
        self.assertEqual(json.loads(ex.to_json(rows)), rows)

    def test_opml_structure(self):
        out = ex.to_opml([{"title": "Hacker News", "url": "https://news.ycombinator.com"}])
        self.assertIn("<opml", out)
        self.assertIn('text="Hacker News"', out)
        self.assertIn('xmlUrl="https://news.ycombinator.com"', out)


class ExportDispatchTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.s.add(db.Task(title="ship it", done=False))
        self.s.add(db.Note(title="idea", content="a note body"))
        acc = db.Account(name="chk", kind="checking", opening=0.0)
        self.s.add(acc)
        self.s.commit()
        self.s.add(
            db.Transaction(account_id=acc.id, date="2026-06-01", amount=-10.0, payee="store")
        )
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_export_tasks_csv(self):
        content, media, fname = ex.export(self.s, "tasks", "csv")
        self.assertIn("ship it", content)
        self.assertEqual(media, "text/csv")
        self.assertTrue(fname.endswith(".csv"))

    def test_export_tasks_json(self):
        content, media, _ = ex.export(self.s, "tasks", "json")
        self.assertTrue(any(r.get("title") == "ship it" for r in json.loads(content)))
        self.assertEqual(media, "application/json")

    def test_export_notes_csv(self):
        content, _, _ = ex.export(self.s, "notes", "csv")
        self.assertIn("idea", content)

    def test_export_transactions_csv(self):
        content, _, _ = ex.export(self.s, "transactions", "csv")
        self.assertIn("store", content)

    def test_export_contacts_vcard(self):
        # this path used to crash: it passed ORM Contact rows to to_vcard (which does
        # c.get(...)), and dropped company/title/address/birthday/website/notes
        self.s.add(db.Contact(name="Ada Lovelace", email="ada@x.com", company="Analytical",
                              notes="enchantress of numbers"))
        self.s.commit()
        content, _, _ = ex.export(self.s, "contacts", "vcard")
        self.assertIn("BEGIN:VCARD", content)
        self.assertIn("Ada Lovelace", content)
        self.assertIn("ada@x.com", content)
        self.assertIn("Analytical", content)  # a field that was silently dropped before

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            ex.export(self.s, "nope", "csv")

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            ex.export(self.s, "tasks", "ical")  # tasks don't support ical

    def test_kinds_listing(self):
        kinds = ex.kinds()
        self.assertIn("tasks", kinds)
        self.assertIn("csv", kinds["tasks"])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        s = db.SessionLocal()
        s.add(db.Task(title="endpoint task", done=False))
        s.commit()
        s.close()
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_export_endpoint(self):
        r = self.c.get("/api/export/tasks", params={"format": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("endpoint task", r.text)


if __name__ == "__main__":
    unittest.main()

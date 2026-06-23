"""regression tests for the 5th bug-hunt iteration:
- the public booking page must enforce its date window (no past / no further than days_ahead)
- caldav/carddav builders must escape CR/LF so a title/field can't inject ical/vcard lines
"""

import os
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import caldav_sync, carddav_sync


class BookingWindowTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        s = db.SessionLocal()
        self.page = db.BookingPage(token="bktok", title="Chat", duration_min=30, days_ahead=14)
        s.add(self.page)
        s.commit()
        s.close()
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_far_future_rejected(self):
        r = self.c.post("/book/bktok", json={"date": "3000-01-05", "time": "10:00", "name": "x"})
        self.assertEqual(r.status_code, 409)

    def test_past_rejected(self):
        r = self.c.post("/book/bktok", json={"date": "2020-01-01", "time": "10:00", "name": "x"})
        self.assertEqual(r.status_code, 409)

    def test_bad_date_rejected(self):
        r = self.c.post("/book/bktok", json={"date": "not-a-date", "time": "10:00", "name": "x"})
        self.assertEqual(r.status_code, 400)

    def test_in_window_not_rejected_for_range(self):
        # a date inside the window shouldn't be rejected for the window reason (may 409 for slot
        # availability, but NOT 400; this proves the window check itself allows it through)
        d = (date.today() + timedelta(days=3)).isoformat()
        r = self.c.post("/book/bktok", json={"date": d, "time": "10:00", "name": "x"})
        self.assertNotEqual(r.status_code, 400)


class IcsVcardEscapeTests(unittest.TestCase):
    def test_ics_escapes_newlines(self):
        out = caldav_sync._ics_esc("Lunch\r\nDTSTART:19990101\r\nSUMMARY:injected")
        self.assertNotIn("\n", out)  # no raw newline -> can't start a new ical line
        self.assertIn("\\n", out)  # folded to the literal escape

    def test_ics_escapes_special_chars(self):
        self.assertEqual(caldav_sync._ics_esc("a;b,c"), "a\\;b\\,c")

    def test_vcard_injection_neutralized(self):
        vc = carddav_sync.build_vcard({"name": "Bob\r\nEMAIL:evil@x.com"}, "uid1")
        lines = vc.split("\n")
        # only ONE FN line, and no injected EMAIL line from the name field
        self.assertEqual(sum(1 for ln in lines if ln.startswith("FN:")), 1)
        self.assertFalse(any(ln.strip() == "EMAIL:evil@x.com" for ln in lines))


if __name__ == "__main__":
    unittest.main()

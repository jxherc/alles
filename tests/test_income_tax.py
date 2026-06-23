"""stage 2f - sub overlap warnings + income classification & quarterly tax planning. RED first."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import income, signals, sub_overlap


class _Base(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.a = db.Account(name="checking", kind="checking", opening=0.0)
        self.s.add(self.a)
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _txn(self, d, amt, payee=""):
        self.s.add(db.Transaction(account_id=self.a.id, date=d, amount=amt, payee=payee))
        self.s.commit()

    def _sub(self, name, price=10.0, active=True):
        s = db.Subscription(
            name=name,
            price=price,
            currency="$",
            cycle="monthly",
            active=active,
            next_due="2026-07-01",
        )
        self.s.add(s)
        self.s.commit()
        return s


class OverlapTests(_Base):
    def test_two_music_services_overlap(self):
        self._sub("Spotify")
        self._sub("Apple Music")
        groups = sub_overlap.overlaps(self.s.query(db.Subscription).all())
        self.assertTrue(any(g["category"] == "music" and len(g["subs"]) == 2 for g in groups))

    def test_single_service_no_overlap(self):
        self._sub("Spotify")
        self._sub("Netflix")  # different categories
        self.assertFalse(sub_overlap.overlaps(self.s.query(db.Subscription).all()))

    def test_inactive_excluded(self):
        self._sub("Spotify")
        self._sub("Apple Music", active=False)
        self.assertFalse(sub_overlap.overlaps(self.s.query(db.Subscription).all()))

    def test_unknown_service_not_grouped(self):
        self._sub("Bob's Random Thing")
        self._sub("Another Mystery")
        self.assertFalse(sub_overlap.overlaps(self.s.query(db.Subscription).all()))

    def test_service_cat_lookup(self):
        self.assertEqual(sub_overlap._service_cat("Netflix Premium"), "video")
        self.assertEqual(sub_overlap._service_cat("Dropbox"), "cloud")
        self.assertEqual(sub_overlap._service_cat("nonsense"), "")


class IncomeTests(_Base):
    def test_classify(self):
        self.assertEqual(income.classify("ACME PAYROLL"), "salary")
        self.assertEqual(income.classify("UPWORK ESCROW"), "freelance")
        self.assertEqual(income.classify("DIVIDEND AAPL"), "investment")
        self.assertEqual(income.classify("IRS TAX REFUND"), "refund")
        self.assertEqual(income.classify("grandma birthday"), "other")

    def test_by_type(self):
        self._txn("2026-06-01", 3000, "ACME PAYROLL")
        self._txn("2026-06-15", 500, "UPWORK")
        self._txn("2026-06-20", -40, "groceries")  # expense ignored
        bt = income.by_type(self.s, "2026-06")
        self.assertEqual(bt["salary"], 3000.0)
        self.assertEqual(bt["freelance"], 500.0)
        self.assertNotIn("other", bt)  # the expense is not income

    def test_rolling_income(self):
        for mo in ("2026-03", "2026-04", "2026-05"):
            self._txn(f"{mo}-10", 3000, "PAYROLL")
        avg = income.rolling_income(self.s, months=3, as_of=datetime.date(2026, 6, 23))
        self.assertEqual(avg, 3000.0)

    def test_current_quarter(self):
        q = income.current_quarter(datetime.date(2026, 7, 10))  # Q3 (Jun1-Aug31), due Sep15
        self.assertEqual(q["label"], "Q3")
        self.assertEqual(q["due"], "2026-09-15")

    def test_quarter_income_and_set_aside(self):
        self._txn("2026-07-01", 4000, "PAYROLL")
        self._txn("2026-08-01", 2000, "UPWORK")  # Q3 total 6000
        as_of = datetime.date(2026, 8, 20)
        self.assertEqual(income.quarter_income(self.s, as_of), 6000.0)
        self.assertEqual(income.set_aside(self.s, as_of, rate=0.25), 1500.0)


class TaxSignalTests(_Base):
    def _collect(self, on, as_of, rate=0.25):
        from unittest import mock

        from core.settings import _defaults

        cfg = dict(_defaults)
        cfg.update({"tax_reminders": on, "tax_setaside_rate": rate})
        with mock.patch("core.settings.load_settings", return_value=cfg):
            return signals._accounts(self.s, as_of)

    def test_reminder_off_by_default(self):
        self._txn("2026-08-01", 5000, "UPWORK")
        sigs = self._collect(False, datetime.date(2026, 9, 10))  # near Q3 due
        self.assertFalse(any("tax" in s["key"] for s in sigs))

    def test_reminder_fires_near_due(self):
        self._txn("2026-08-01", 5000, "UPWORK")
        sigs = self._collect(True, datetime.date(2026, 9, 10))  # within window of Sep 15
        self.assertTrue(any(s["key"].startswith("tax_quarter:") for s in sigs))

    def test_reminder_silent_when_far(self):
        self._txn("2026-07-01", 5000, "UPWORK")
        sigs = self._collect(True, datetime.date(2026, 7, 20))  # far from any due date
        self.assertFalse(any(s["key"].startswith("tax_quarter:") for s in sigs))


if __name__ == "__main__":
    unittest.main()

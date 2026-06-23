"""stage 2b - forecast: category breakdown + what-if. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import forecast

TODAY = datetime.date(2026, 6, 23)


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.a = db.Account(name="checking", kind="checking", currency="$", opening=0.0)
        self.s.add(self.a)
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _txn(self, d, amt, cat="groceries", payee=""):
        self.s.add(
            db.Transaction(account_id=self.a.id, date=d, amount=amt, category=cat, payee=payee)
        )
        self.s.commit()

    def test_category_averages_3_months(self):
        self._txn("2026-03-10", -90, "groceries")
        self._txn("2026-04-10", -120, "groceries")
        self._txn("2026-05-10", -90, "groceries")
        avg = forecast.category_averages(self.s, months=3, as_of=TODAY)
        self.assertAlmostEqual(avg["groceries"], 100.0)  # (90+120+90)/3

    def test_category_averages_excludes_income(self):
        self._txn("2026-05-01", 2000, "salary")
        self._txn("2026-05-10", -50, "coffee")
        avg = forecast.category_averages(self.s, months=3, as_of=TODAY)
        self.assertNotIn("salary", avg)
        self.assertIn("coffee", avg)

    def test_category_averages_empty(self):
        self.assertEqual(forecast.category_averages(self.s, months=3, as_of=TODAY), {})

    def test_category_averages_only_last_n_months(self):
        self._txn("2026-01-10", -300, "groceries")  # older than 3 months before June -> ignored
        self._txn("2026-05-10", -60, "groceries")
        avg = forecast.category_averages(self.s, months=3, as_of=TODAY)
        self.assertAlmostEqual(avg["groceries"], 20.0)  # only the 60, /3 months

    def test_scenario_skip_removes_occurrence(self):
        occ = [
            {"date": "2026-06-25", "amount": -15.0, "payee": "netflix"},
            {"date": "2026-06-28", "amount": -1200.0, "payee": "rent"},
        ]
        out = forecast.apply_scenario(occ, skip_payees=["netflix"])
        payees = [o["payee"] for o in out]
        self.assertNotIn("netflix", payees)
        self.assertIn("rent", payees)

    def test_scenario_skip_is_case_insensitive_substring(self):
        occ = [{"date": "2026-06-25", "amount": -15.0, "payee": "Netflix Inc"}]
        self.assertEqual(forecast.apply_scenario(occ, skip_payees=["netflix"]), [])

    def test_scenario_income_delta_appends(self):
        occ = [{"date": "2026-06-25", "amount": -15.0, "payee": "x"}]
        out = forecast.apply_scenario(occ, income_delta=500.0, at="2026-06-30")
        self.assertTrue(any(o["amount"] == 500.0 for o in out))

    def test_scenario_income_delta_zero_noop(self):
        occ = [{"date": "2026-06-25", "amount": -15.0, "payee": "x"}]
        self.assertEqual(forecast.apply_scenario(occ, income_delta=0.0), occ)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient

        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from app import app

        self.c = TestClient(app)
        self.s = db.SessionLocal()
        self.a = db.Account(name="checking", kind="checking", currency="$", opening=1000.0)
        self.s.add(self.a)
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _recurring(self, payee, amount, next_date):
        self.s.add(
            db.RecurringTxn(
                account_id=self.a.id,
                payee=payee,
                amount=amount,
                cycle="monthly",
                next_date=next_date,
                active=True,
            )
        )
        self.s.commit()

    def test_forecast_returns_categories(self):
        self.s.add(
            db.Transaction(account_id=self.a.id, date="2026-05-10", amount=-80, category="coffee")
        )
        self.s.commit()
        r = self.c.get("/api/money/forecast?month=2026-06&as_of=2026-06-01").json()
        self.assertIn("categories", r)

    def test_skip_raises_projected(self):
        self._recurring("rent", -500.0, "2026-06-10")
        base = self.c.get("/api/money/forecast?month=2026-06&as_of=2026-06-01").json()["projected"]
        skipped = self.c.get("/api/money/forecast?month=2026-06&as_of=2026-06-01&skip=rent").json()[
            "projected"
        ]
        self.assertGreater(skipped, base)  # skipping a -500 bill leaves more money

    def test_income_delta_raises_projected(self):
        base = self.c.get("/api/money/forecast?month=2026-06&as_of=2026-06-01").json()["projected"]
        boosted = self.c.get(
            "/api/money/forecast?month=2026-06&as_of=2026-06-01&income_delta=500"
        ).json()["projected"]
        self.assertAlmostEqual(boosted - base, 500.0, places=1)


if __name__ == "__main__":
    unittest.main()

"""stage 2c - spending anomaly alerts + merchant insights. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import money_stats, signals

TODAY = datetime.date(2026, 6, 23)


class StatsTests(unittest.TestCase):
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

    def _txn(self, d, amt, cat="groceries", payee=""):
        self.s.add(
            db.Transaction(account_id=self.a.id, date=d, amount=amt, category=cat, payee=payee)
        )
        self.s.commit()

    def _baseline_groceries(self):
        for d in ("2026-03-10", "2026-04-10", "2026-05-10"):
            self._txn(d, -100, "groceries")

    def test_category_anomaly_spike(self):
        self._baseline_groceries()
        self._txn("2026-06-12", -300, "groceries")  # 3x baseline
        anoms = money_stats.category_anomalies(self.s, as_of=TODAY)
        self.assertTrue(any(a["category"] == "groceries" for a in anoms))
        g = next(a for a in anoms if a["category"] == "groceries")
        self.assertGreaterEqual(g["ratio"], 1.5)

    def test_category_anomaly_cur_param_equivalent(self):
        # passing a precomputed spend dict (cur=) must give the same result as computing
        # it internally — the optimization that avoids a redundant scan in signals.gather
        self._baseline_groceries()
        self._txn("2026-06-12", -300, "groceries")
        from routes.money import _spending_by_cat

        cur = _spending_by_cat(self.s, TODAY.strftime("%Y-%m"))
        self.assertEqual(
            money_stats.category_anomalies(self.s, as_of=TODAY),
            money_stats.category_anomalies(self.s, as_of=TODAY, cur=cur),
        )

    def test_category_normal_not_flagged(self):
        self._baseline_groceries()
        self._txn("2026-06-12", -110, "groceries")  # ~1.1x, within tolerance
        self.assertFalse(money_stats.category_anomalies(self.s, as_of=TODAY))

    def test_category_anomaly_min_amount(self):
        for d in ("2026-03-10", "2026-04-10", "2026-05-10"):
            self._txn(d, -5, "coffee")
        self._txn("2026-06-12", -20, "coffee")  # 4x but tiny absolute -> below min_amount
        self.assertFalse(money_stats.category_anomalies(self.s, as_of=TODAY, min_amount=50))

    def test_category_no_baseline_not_flagged(self):
        self._txn("2026-06-12", -300, "newcat")  # no history -> no baseline -> not an anomaly
        self.assertFalse(
            [
                a
                for a in money_stats.category_anomalies(self.s, as_of=TODAY)
                if a["category"] == "newcat"
            ]
        )

    def test_new_merchant_detected(self):
        self._txn("2026-06-12", -40, "shopping", "NEW PLACE #1")
        nm = money_stats.new_merchants(self.s, as_of=TODAY)
        self.assertTrue(any("new place" in m["merchant"] for m in nm))

    def test_recurring_merchant_not_new(self):
        self._txn("2026-04-10", -40, "shopping", "Old Shop")
        self._txn("2026-06-12", -40, "shopping", "Old Shop")
        nm = money_stats.new_merchants(self.s, as_of=TODAY)
        self.assertFalse(any("old shop" in m["merchant"] for m in nm))

    def test_new_merchant_min_amount(self):
        self._txn("2026-06-12", -5, "shopping", "Tiny Shop")  # below min
        self.assertFalse(money_stats.new_merchants(self.s, as_of=TODAY, min_amount=20))


class SignalIntegrationTests(unittest.TestCase):
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

    def _txn(self, d, amt, cat="groceries", payee=""):
        self.s.add(
            db.Transaction(account_id=self.a.id, date=d, amount=amt, category=cat, payee=payee)
        )
        self.s.commit()

    def test_budget_collector_emits_anomaly_signal(self):
        for d in ("2026-03-10", "2026-04-10", "2026-05-10"):
            self._txn(d, -100, "groceries")
        self._txn("2026-06-12", -300, "groceries", "MEGA MART")
        sigs = signals._budget(self.s, TODAY)
        keys = [s["key"] for s in sigs]
        self.assertTrue(any(k.startswith("anomaly:cat:groceries") for k in keys))
        # anomaly signals ride the budget family (money proactive toggle)
        self.assertTrue(all(s["category"] == "budget" for s in sigs))

    def test_budget_collector_emits_new_merchant_signal(self):
        self._txn("2026-06-12", -60, "shopping", "BRAND NEW STORE")
        sigs = signals._budget(self.s, TODAY)
        self.assertTrue(any(s["key"].startswith("anomaly:merchant:") for s in sigs))


if __name__ == "__main__":
    unittest.main()

"""stage 2a - NL spending search + insights. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import money_query as mq

TODAY = datetime.date(2026, 6, 23)


class ParsePeriodTests(unittest.TestCase):
    def _p(self, text):
        return mq.parse_period(text, today=TODAY)

    def test_this_month(self):
        s, e, label = self._p("how much this month")
        self.assertEqual((s, e), (datetime.date(2026, 6, 1), TODAY))
        self.assertEqual(label, "this month")

    def test_last_month(self):
        s, e, label = self._p("groceries last month")
        self.assertEqual((s, e), (datetime.date(2026, 5, 1), datetime.date(2026, 5, 31)))
        self.assertEqual(label, "last month")

    def test_this_year(self):
        s, e, label = self._p("spending this year")
        self.assertEqual((s, e), (datetime.date(2026, 1, 1), TODAY))
        self.assertEqual(label, "this year")

    def test_last_year(self):
        s, e, label = self._p("how much last year")
        self.assertEqual((s, e), (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31)))

    def test_last_n_days(self):
        s, e, label = self._p("spending in the last 30 days")
        self.assertEqual((s, e), (datetime.date(2026, 5, 24), TODAY))

    def test_named_month_past_is_this_year(self):
        s, e, label = self._p("what did i spend in march")
        self.assertEqual((s, e), (datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)))
        self.assertEqual(label, "march")

    def test_named_month_future_is_last_year(self):
        s, e, label = self._p("spending in december")  # december > june -> last year
        self.assertEqual((s, e), (datetime.date(2025, 12, 1), datetime.date(2025, 12, 31)))

    def test_default_is_this_month(self):
        s, e, label = self._p("coffee")
        self.assertEqual((s, e), (datetime.date(2026, 6, 1), TODAY))
        self.assertEqual(label, "this month")


class RollupTests(unittest.TestCase):
    def test_norm_payee_strips_store_numbers(self):
        self.assertEqual(mq._norm_payee("STARBUCKS #1234"), "starbucks")
        self.assertEqual(mq._norm_payee("Amazon.com*A1B2C"), "amazon.com")

    def test_merchant_rollup_sums_and_ranks(self):
        txns = [
            type("T", (), {"payee": "STARBUCKS #1", "amount": -5.0, "category": "coffee"})(),
            type("T", (), {"payee": "starbucks #2", "amount": -3.0, "category": "coffee"})(),
            type("T", (), {"payee": "Whole Foods", "amount": -40.0, "category": "groceries"})(),
            type("T", (), {"payee": "paycheck", "amount": 100.0, "category": "income"})(),
        ]
        roll = mq.merchant_rollup(txns)
        self.assertEqual(roll[0], ("whole foods", 40.0))
        self.assertEqual(dict(roll)["starbucks"], 8.0)  # merged + summed
        self.assertNotIn("paycheck", dict(roll))  # income excluded

    def test_category_breakdown(self):
        txns = [
            type("T", (), {"amount": -5.0, "category": "coffee"})(),
            type("T", (), {"amount": -7.0, "category": "coffee"})(),
            type("T", (), {"amount": -40.0, "category": "groceries"})(),
        ]
        cb = dict(mq.category_breakdown(txns))
        self.assertEqual(cb["coffee"], 12.0)
        self.assertEqual(cb["groceries"], 40.0)


class AnswerTests(unittest.TestCase):
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

    def _txn(self, d, amt, payee="", cat=""):
        self.s.add(
            db.Transaction(account_id=self.a.id, date=d, amount=amt, payee=payee, category=cat)
        )
        self.s.commit()

    def test_answer_filters_by_period(self):
        self._txn("2026-06-10", -20.0, "store", "groceries")  # this month
        self._txn("2026-05-10", -99.0, "store", "groceries")  # last month
        out = mq.answer(self.s, "groceries last month", today=TODAY)
        self.assertIn("99", out)
        self.assertNotIn("20.00", out)  # this-month txn excluded from a last-month query

    def test_answer_merchant_rollup(self):
        self._txn("2026-06-01", -5.0, "STARBUCKS #1", "coffee")
        self._txn("2026-06-02", -4.0, "starbucks #2", "coffee")
        out = mq.answer(self.s, "how much at starbucks this month", today=TODAY)
        self.assertIn("starbucks", out.lower())
        self.assertIn("9", out)  # 5 + 4 merged

    def test_answer_compare_periods(self):
        self._txn("2026-06-05", -30.0, "x", "groceries")  # this month
        self._txn("2026-05-05", -50.0, "x", "groceries")  # last month
        out = mq.answer(self.s, "compare groceries this month vs last month", today=TODAY)
        self.assertIn("30", out)
        self.assertIn("50", out)


if __name__ == "__main__":
    unittest.main()

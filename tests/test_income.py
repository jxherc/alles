"""coverage for services/income.py — income classification + US estimated-tax quarter math.
the quarter boundaries are uneven (Q1 jan-mar, Q2 apr-may, Q3 jun-aug, Q4 sep-dec) and Q4 is
due in the next year, so they're easy to break silently. these lock the behavior in."""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.database as db
from services import income


class ClassifyTests(unittest.TestCase):
    def test_each_type_matches(self):
        self.assertEqual(income.classify("ADP Payroll"), "salary")
        self.assertEqual(income.classify("Upwork payout"), "freelance")
        self.assertEqual(income.classify("Vanguard dividend"), "investment")
        self.assertEqual(income.classify("IRS refund"), "refund")

    def test_unknown_is_other(self):
        self.assertEqual(income.classify("Some Random LLC"), "other")
        self.assertEqual(income.classify(""), "other")
        self.assertEqual(income.classify(None), "other")

    def test_first_match_wins(self):
        # contains both a salary and a freelance keyword; salary rule is first
        self.assertEqual(income.classify("payroll via stripe"), "salary")


class QuarterTests(unittest.TestCase):
    def test_current_quarter_each(self):
        self.assertEqual(income.current_quarter(datetime.date(2026, 2, 15))["label"], "Q1")
        self.assertEqual(income.current_quarter(datetime.date(2026, 5, 1))["label"], "Q2")
        self.assertEqual(income.current_quarter(datetime.date(2026, 7, 4))["label"], "Q3")
        self.assertEqual(income.current_quarter(datetime.date(2026, 11, 1))["label"], "Q4")

    def test_quarter_boundaries_are_contiguous(self):
        # the last day of one quarter and the first of the next must not fall in a gap
        self.assertEqual(income.current_quarter(datetime.date(2026, 3, 31))["label"], "Q1")
        self.assertEqual(income.current_quarter(datetime.date(2026, 4, 1))["label"], "Q2")
        self.assertEqual(income.current_quarter(datetime.date(2026, 5, 31))["label"], "Q2")
        self.assertEqual(income.current_quarter(datetime.date(2026, 6, 1))["label"], "Q3")

    def test_q4_due_rolls_into_next_year(self):
        q = income.current_quarter(datetime.date(2026, 10, 1))
        self.assertEqual(q["due"], "2027-01-15")
        self.assertEqual(q["start"], "2026-09-01")

    def test_q1_due_same_year(self):
        self.assertEqual(income.current_quarter(datetime.date(2026, 1, 10))["due"], "2026-04-15")

    def test_upcoming_due_in_window(self):
        # 14 days before the Q1 due date (apr 15)
        u = income.upcoming_due(datetime.date(2026, 4, 1), window_days=21)
        self.assertEqual(u["label"], "Q1")
        self.assertEqual(u["due"], "2026-04-15")
        self.assertEqual(u["days"], 14)

    def test_upcoming_due_crosses_year(self):
        # late december → the Q4 payment due jan 15 next year is what's near
        u = income.upcoming_due(datetime.date(2026, 12, 30), window_days=21)
        self.assertEqual(u["label"], "Q4")
        self.assertEqual(u["due"], "2027-01-15")
        self.assertEqual(u["start"], "2026-09-01")

    def test_upcoming_due_none_when_far(self):
        # mid-quarter, no due date within 21 days
        self.assertIsNone(income.upcoming_due(datetime.date(2026, 2, 1), window_days=21))


class DbTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.acc = db.Account(name="checking", kind="checking", currency="$", opening=0.0)
        self.s.add(self.acc)
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _txn(self, date_str, amount, payee="", transfer_id=None):
        self.s.add(
            db.Transaction(
                account_id=self.acc.id, date=date_str, amount=amount, payee=payee,
                transfer_id=transfer_id,
            )
        )
        self.s.commit()

    def test_by_type_groups_and_filters_month(self):
        self._txn("2026-06-01", 3000, "ADP payroll")
        self._txn("2026-06-10", 500, "Upwork")
        self._txn("2026-05-30", 999, "ADP payroll")  # different month, excluded
        out = income.by_type(self.s, "2026-06")
        self.assertEqual(out.get("salary"), 3000.0)
        self.assertEqual(out.get("freelance"), 500.0)
        self.assertNotIn("2026-05", str(out))

    def test_income_excludes_spending_and_transfers(self):
        self._txn("2026-06-01", -50, "coffee")  # expense, negative
        self._txn("2026-06-02", 200, "transfer in", transfer_id="tr1")  # transfer, excluded
        self._txn("2026-06-03", 100, "Stripe invoice")
        out = income.by_type(self.s, "2026-06")
        self.assertEqual(out, {"freelance": 100.0})

    def test_rolling_income_averages_over_months(self):
        # as_of july → last 3 complete months = apr, may, jun
        self._txn("2026-04-15", 3000, "salary")
        self._txn("2026-05-15", 3000, "salary")
        self._txn("2026-06-15", 3000, "salary")
        avg = income.rolling_income(self.s, months=3, as_of=datetime.date(2026, 7, 1))
        self.assertAlmostEqual(avg, 3000.0)

    def test_quarter_income_and_set_aside(self):
        # Q3 earning window jun1-aug31; as_of jul 15 caps at jul 15
        self._txn("2026-06-10", 2000, "salary")
        self._txn("2026-07-10", 2000, "salary")
        self._txn("2026-08-20", 5000, "salary")  # after as_of, excluded
        as_of = datetime.date(2026, 7, 15)
        self.assertEqual(income.quarter_income(self.s, as_of), 4000.0)
        self.assertEqual(income.set_aside(self.s, as_of, rate=0.25), 1000.0)


if __name__ == "__main__":
    unittest.main()

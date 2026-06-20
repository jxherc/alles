import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Account, Budget, Transaction, TxnSplit
from routes import money


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    for M in (Account, Budget, Transaction, TxnSplit):
        M.__table__.create(eng)
    return sessionmaker(bind=eng)()


class MoneySummaryTests(unittest.TestCase):
    def _seed(self):
        db = _mkdb()
        a = Account(name="Checking", kind="checking", currency="$", opening=100.0)
        db.add(a)
        db.commit()
        db.refresh(a)
        db.add_all(
            [
                Transaction(account_id=a.id, date="2026-06-05", amount=2000.0, category="salary"),
                Transaction(account_id=a.id, date="2026-06-10", amount=-50.0, category="food"),
                Transaction(account_id=a.id, date="2026-06-12", amount=-30.0, category="food"),
                Transaction(account_id=a.id, date="2026-05-01", amount=-100.0, category="rent"),
            ]
        )
        db.commit()
        return db

    def test_income_expense_net(self):
        s = money.summary("2026-06", self._seed())
        self.assertEqual(s["income"], 2000.0)
        self.assertEqual(s["expense"], 80.0)  # only June expenses
        self.assertEqual(s["net"], 1920.0)

    def test_by_category(self):
        s = money.summary("2026-06", self._seed())
        cats = dict(s["by_category"])
        self.assertEqual(cats["food"], 80.0)
        self.assertNotIn("rent", cats)  # different month

    def test_net_worth_includes_opening_and_all_txns(self):
        s = money.summary("2026-06", self._seed())
        # 100 opening + (2000 - 50 - 30 - 100) across all months = 1920
        self.assertEqual(s["net_worth"], 1920.0)

    def test_empty_db_zeroes(self):
        db = _mkdb()
        s = money.summary("2026-06", db)
        self.assertEqual(s["income"], 0.0)
        self.assertEqual(s["expense"], 0.0)
        self.assertEqual(s["net_worth"], 0.0)

    def test_transfers_excluded_from_income_expense(self):
        db = _mkdb()
        a = Account(name="A", kind="checking", currency="$", opening=0.0)
        b = Account(name="B", kind="savings", currency="$", opening=0.0)
        db.add_all([a, b])
        db.commit()
        tid = "some-transfer-id"
        db.add_all(
            [
                Transaction(account_id=a.id, date="2026-06-01", amount=-500.0, transfer_id=tid),
                Transaction(account_id=b.id, date="2026-06-01", amount=500.0, transfer_id=tid),
            ]
        )
        db.commit()
        s = money.summary("2026-06", db)
        # transfers don't count as income or expense
        self.assertEqual(s["income"], 0.0)
        self.assertEqual(s["expense"], 0.0)

    def test_budget_shows_spent_vs_limit(self):
        db = _mkdb()
        a = Account(name="C", kind="checking", currency="$", opening=0.0)
        db.add(a)
        db.commit()
        db.add(Budget(category="food", limit_amt=200.0))
        db.add(Transaction(account_id=a.id, date="2026-06-05", amount=-75.0, category="food"))
        db.commit()
        s = money.summary("2026-06", db)
        budgets = {b["category"]: b for b in s["budgets"]}
        self.assertIn("food", budgets)
        self.assertEqual(budgets["food"]["limit"], 200.0)
        self.assertEqual(budgets["food"]["spent"], 75.0)

    def test_trend_includes_6_months(self):
        db = _mkdb()
        s = money.summary("2026-06", db)
        self.assertEqual(len(s["trend"]), 6)
        months = [r["month"] for r in s["trend"]]
        self.assertIn("2026-06", months)

    def test_categorize_case_insensitive(self):

        class FakeRule:
            match = "amazon"
            category = "shopping"

        rules = [FakeRule()]
        self.assertEqual(money._categorize("AMAZON.COM", rules), "shopping")
        self.assertEqual(money._categorize("starbucks", rules), "")

    def test_add_months_boundary(self):
        from datetime import date

        # jan 31 + 1 month → feb 28 (not crash)
        result = money._add_months(date(2026, 1, 31), 1)
        self.assertEqual(result, date(2026, 2, 28))


if __name__ == "__main__":
    unittest.main()

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Account, Transaction, Budget
from routes import money


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    for M in (Account, Transaction, Budget):
        M.__table__.create(eng)
    return sessionmaker(bind=eng)()


class MoneySummaryTests(unittest.TestCase):
    def _seed(self):
        db = _mkdb()
        a = Account(name="Checking", kind="checking", currency="$", opening=100.0)
        db.add(a); db.commit(); db.refresh(a)
        db.add_all([
            Transaction(account_id=a.id, date="2026-06-05", amount=2000.0, category="salary"),
            Transaction(account_id=a.id, date="2026-06-10", amount=-50.0, category="food"),
            Transaction(account_id=a.id, date="2026-06-12", amount=-30.0, category="food"),
            Transaction(account_id=a.id, date="2026-05-01", amount=-100.0, category="rent"),
        ])
        db.commit()
        return db

    def test_income_expense_net(self):
        s = money.summary("2026-06", self._seed())
        self.assertEqual(s["income"], 2000.0)
        self.assertEqual(s["expense"], 80.0)          # only June expenses
        self.assertEqual(s["net"], 1920.0)

    def test_by_category(self):
        s = money.summary("2026-06", self._seed())
        cats = dict(s["by_category"])
        self.assertEqual(cats["food"], 80.0)
        self.assertNotIn("rent", cats)                # different month

    def test_net_worth_includes_opening_and_all_txns(self):
        s = money.summary("2026-06", self._seed())
        # 100 opening + (2000 - 50 - 30 - 100) across all months = 1920
        self.assertEqual(s["net_worth"], 1920.0)


if __name__ == "__main__":
    unittest.main()

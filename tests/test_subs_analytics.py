import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Subscription
from routes import subscriptions as S


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    Subscription.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _mkdb_full():
    from core.database import Account, Transaction

    eng = create_engine("sqlite:///:memory:")
    for m in (Account, Transaction, Subscription):
        m.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _sub(**kw):
    base = dict(
        name="x", price=0, cycle="monthly", cycle_days=30, next_due="2026-06-14", active=True
    )
    base.update(kw)
    return Subscription(**base)


class MonthlyCostTests(unittest.TestCase):
    def test_cycle_normalization(self):
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="monthly", price=10)), 10)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="yearly", price=120)), 10)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="quarterly", price=30)), 10)
        self.assertAlmostEqual(
            S._monthly_cost(_sub(cycle="weekly", price=10)), 10 * 52 / 12, places=2
        )
        self.assertAlmostEqual(
            S._monthly_cost(_sub(cycle="custom", price=10, cycle_days=60)),
            10 * 30.44 / 60,
            places=2,
        )


class AnalyticsTests(unittest.TestCase):
    def test_breakdown_excludes_inactive_and_sorts(self):
        db = _mkdb()
        db.add_all(
            [
                _sub(name="Netflix", price=15, category="streaming"),
                _sub(name="Spotify", price=10, category="streaming"),
                _sub(name="Domain", price=12, cycle="yearly", cycle_days=365, category="hosting"),
                _sub(name="Old", price=99, category="x", active=False),
            ]
        )
        db.commit()
        a = S.analytics(db)
        self.assertEqual(a["count"], 3)  # inactive dropped
        cats = {c["name"]: c["monthly"] for c in a["by_category"]}
        self.assertAlmostEqual(cats["streaming"], 25, places=1)
        self.assertAlmostEqual(cats["hosting"], 1.0, places=1)  # 12/12 per month
        self.assertEqual(a["by_category"][0]["name"], "streaming")  # biggest first
        self.assertAlmostEqual(a["monthly_total"], 26.0, places=1)


class AutoPostTests(unittest.TestCase):
    def _setup(self, days_ago=3, cycle="monthly", account=True):
        from datetime import date, timedelta
        from core.database import Account, Transaction

        db = _mkdb_full()
        acct = Account(name="checking", opening=0.0)
        db.add(acct)
        db.commit()
        due = (date.today() - timedelta(days=days_ago)).isoformat()
        sub = _sub(
            name="Netflix",
            price=15,
            cycle=cycle,
            account_id=acct.id if account else "",
            next_due=due,
        )
        db.add(sub)
        db.commit()
        return db, sub, acct, due

    def test_posts_charge_to_linked_account(self):
        from datetime import date
        from core.database import Transaction

        db, sub, acct, due = self._setup()
        changed = S._roll_and_post(sub, date.today(), db)
        db.commit()
        self.assertTrue(changed)
        txns = db.query(Transaction).all()
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].amount, -15)  # expense = negative
        self.assertEqual(txns[0].payee, "Netflix")
        self.assertEqual(txns[0].date, due)
        self.assertEqual(txns[0].account_id, acct.id)
        self.assertEqual(sub.last_posted_due, due)
        self.assertGreater(sub.next_due, due)  # rolled forward

    def test_idempotent_second_roll_no_double_post(self):
        from datetime import date
        from core.database import Transaction

        db, sub, acct, due = self._setup()
        S._roll_and_post(sub, date.today(), db)
        db.commit()
        again = S._roll_and_post(sub, date.today(), db)
        db.commit()
        self.assertFalse(again)  # already future, nothing due
        self.assertEqual(len(db.query(Transaction).all()), 1)

    def test_unlinked_sub_rolls_but_posts_nothing(self):
        from datetime import date
        from core.database import Transaction

        db, sub, acct, due = self._setup(account=False)
        changed = S._roll_and_post(sub, date.today(), db)
        db.commit()
        self.assertTrue(changed)
        self.assertEqual(db.query(Transaction).count(), 0)


if __name__ == "__main__":
    unittest.main()

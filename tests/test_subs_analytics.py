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
    from core.database import Account, SubPayment, Transaction

    eng = create_engine("sqlite:///:memory:")
    for m in (Account, Transaction, Subscription, SubPayment):
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

    def test_zero_price(self):
        self.assertEqual(S._monthly_cost(_sub(price=0, cycle="yearly")), 0)

    def test_custom_cycle_days_1(self):
        # daily billing — 30.44 per month
        self.assertAlmostEqual(
            S._monthly_cost(_sub(cycle="custom", price=1, cycle_days=1)), 30.44, places=1
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

    def test_analytics_empty(self):
        db = _mkdb()
        a = S.analytics(db)
        self.assertEqual(a["count"], 0)
        self.assertEqual(a["monthly_total"], 0)
        self.assertEqual(a["by_category"], [])

    def test_analytics_by_cycle_grouping(self):
        db = _mkdb()
        db.add_all(
            [
                _sub(name="A", price=10, cycle="monthly"),
                _sub(name="B", price=120, cycle="yearly"),
            ]
        )
        db.commit()
        a = S.analytics(db)
        by_cycle = {c["name"]: c["monthly"] for c in a["by_cycle"]}
        self.assertIn("monthly", by_cycle)
        self.assertIn("yearly", by_cycle)
        self.assertAlmostEqual(by_cycle["monthly"], 10, places=1)
        self.assertAlmostEqual(by_cycle["yearly"], 10, places=1)

    def test_analytics_uncategorized_bucket(self):
        # sub with no category goes into 'uncategorized'
        db = _mkdb()
        db.add(_sub(name="mystery", price=5, category=""))
        db.commit()
        a = S.analytics(db)
        cats = {c["name"] for c in a["by_category"]}
        self.assertIn("uncategorized", cats)


class AutoPostTests(unittest.TestCase):
    def _setup(self, days_ago=3, cycle="monthly", account=True):
        from datetime import date, timedelta

        from core.database import Account

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

    def test_autopost_records_a_payment(self):
        from datetime import date

        from core.database import SubPayment

        db, sub, acct, due = self._setup()
        S._roll_and_post(sub, date.today(), db)
        db.commit()
        pays = db.query(SubPayment).filter_by(sub_id=sub.id).all()
        self.assertEqual(len(pays), 1)  # auto-posted renewal now has a history row + undo path
        self.assertTrue(pays[0].txn_id)

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

    def test_inactive_sub_not_rolled(self):
        from datetime import date

        db, sub, acct, due = self._setup()
        sub.active = False
        db.commit()
        changed = S._roll_and_post(sub, date.today(), db)
        self.assertFalse(changed)
        self.assertEqual(sub.next_due, due)  # unchanged


if __name__ == "__main__":
    unittest.main()

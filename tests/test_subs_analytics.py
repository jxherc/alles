import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Subscription
from routes import subscriptions as S


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    Subscription.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _sub(**kw):
    base = dict(name="x", price=0, cycle="monthly", cycle_days=30, next_due="2026-06-14", active=True)
    base.update(kw)
    return Subscription(**base)


class MonthlyCostTests(unittest.TestCase):
    def test_cycle_normalization(self):
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="monthly", price=10)), 10)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="yearly", price=120)), 10)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="quarterly", price=30)), 10)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="weekly", price=10)), 10 * 52 / 12, places=2)
        self.assertAlmostEqual(S._monthly_cost(_sub(cycle="custom", price=10, cycle_days=60)), 10 * 30.44 / 60, places=2)


class AnalyticsTests(unittest.TestCase):
    def test_breakdown_excludes_inactive_and_sorts(self):
        db = _mkdb()
        db.add_all([
            _sub(name="Netflix", price=15, category="streaming"),
            _sub(name="Spotify", price=10, category="streaming"),
            _sub(name="Domain", price=12, cycle="yearly", cycle_days=365, category="hosting"),
            _sub(name="Old", price=99, category="x", active=False),
        ])
        db.commit()
        a = S.analytics(db)
        self.assertEqual(a["count"], 3)                      # inactive dropped
        cats = {c["name"]: c["monthly"] for c in a["by_category"]}
        self.assertAlmostEqual(cats["streaming"], 25, places=1)
        self.assertAlmostEqual(cats["hosting"], 1.0, places=1)   # 12/12 per month
        self.assertEqual(a["by_category"][0]["name"], "streaming")  # biggest first
        self.assertAlmostEqual(a["monthly_total"], 26.0, places=1)


if __name__ == "__main__":
    unittest.main()

"""stage 2e - tag rules + tag hierarchy + tag budgeting. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import signals, tag_rules

TODAY = datetime.date(2026, 6, 23)


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

    def _txn(self, d, amt, tags="", payee="", cat=""):
        self.s.add(
            db.Transaction(
                account_id=self.a.id, date=d, amount=amt, tags=tags, payee=payee, category=cat
            )
        )
        self.s.commit()

    def _rule(self, match, tags):
        r = db.TagRule(match=match, tags=tags)
        self.s.add(r)
        self.s.commit()
        return r


class ApplyTests(_Base):
    def test_apply_adds_tag_from_payee(self):
        self._rule("starbucks", "coffee")
        out = tag_rules.apply_rules("STARBUCKS #42", self.s.query(db.TagRule).all())
        self.assertEqual(out, "coffee")

    def test_apply_merges_with_existing(self):
        self._rule("starbucks", "coffee")
        out = tag_rules.apply_rules("STARBUCKS", self.s.query(db.TagRule).all(), existing="treat")
        self.assertEqual(set(out.split(",")), {"treat", "coffee"})

    def test_apply_dedupes(self):
        self._rule("starbucks", "coffee")
        out = tag_rules.apply_rules("STARBUCKS", self.s.query(db.TagRule).all(), existing="coffee")
        self.assertEqual(out, "coffee")

    def test_apply_no_match(self):
        self._rule("starbucks", "coffee")
        out = tag_rules.apply_rules("SHELL GAS", self.s.query(db.TagRule).all())
        self.assertEqual(out, "")

    def test_apply_multiple_rules_and_multitag(self):
        self._rule("amazon", "shopping,online")
        self._rule("prime", "subscription")
        out = tag_rules.apply_rules("AMAZON PRIME", self.s.query(db.TagRule).all())
        self.assertEqual(set(out.split(",")), {"shopping", "online", "subscription"})


class HierarchyTests(_Base):
    def test_ancestors(self):
        self.assertEqual(
            tag_rules.ancestors("food/coffee/latte"), ["food/coffee/latte", "food/coffee", "food"]
        )

    def test_ancestors_flat(self):
        self.assertEqual(tag_rules.ancestors("food"), ["food"])

    def test_expand_includes_parents(self):
        self.assertEqual(tag_rules.expand("food/coffee"), {"food/coffee", "food"})

    def test_spending_by_tag_rolls_up(self):
        self._txn("2026-06-10", -10, tags="food/coffee")
        self._txn("2026-06-11", -30, tags="food/groceries")
        by = tag_rules.spending_by_tag(self.s, "2026-06")
        self.assertEqual(by["food"], 40.0)  # both roll up to food
        self.assertEqual(by["food/coffee"], 10.0)

    def test_spending_by_tag_excludes_income_and_transfers(self):
        self._txn("2026-06-10", 500, tags="food")  # income, ignored
        self._txn("2026-06-11", -20, tags="food")
        by = tag_rules.spending_by_tag(self.s, "2026-06")
        self.assertEqual(by.get("food", 0.0), 20.0)


class TagBudgetTests(_Base):
    def test_tag_budget_signal_fires(self):
        self.s.add(db.Budget(category="", tag="food", limit_amt=50.0))
        self.s.commit()
        self._txn("2026-06-10", -40, tags="food/coffee")
        self._txn("2026-06-11", -30, tags="food/groceries")  # food total 70 > 50
        sigs = signals._budget(self.s, TODAY)
        self.assertTrue(any(s["key"].startswith("budget_over:tag:food") for s in sigs))

    def test_tag_budget_under_no_signal(self):
        self.s.add(db.Budget(category="", tag="food", limit_amt=500.0))
        self.s.commit()
        self._txn("2026-06-10", -40, tags="food/coffee")
        sigs = signals._budget(self.s, TODAY)
        self.assertFalse(any(s["key"].startswith("budget_over:tag:food") for s in sigs))


class EndpointTests(_Base):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def test_create_txn_applies_tag_rule(self):
        self._rule("starbucks", "coffee")
        r = self.c.post(
            "/api/money/transactions",
            json={
                "account_id": self.a.id,
                "date": "2026-06-20",
                "amount": -5,
                "payee": "Starbucks",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tags"], "coffee")

    def test_tag_rules_crud_and_bulk_apply(self):
        self.c.post("/api/money/tag-rules", json={"match": "uber", "tags": "transport"})
        self.assertTrue(
            any(x["match"] == "uber" for x in self.c.get("/api/money/tag-rules").json())
        )
        self._txn("2026-06-10", -12, payee="UBER TRIP")  # no tag yet
        out = self.c.post("/api/money/tag-rules/apply").json()
        self.assertEqual(out["updated"], 1)
        t = self.s.query(db.Transaction).filter(db.Transaction.payee == "UBER TRIP").first()
        self.s.refresh(t)
        self.assertEqual(t.tags, "transport")


if __name__ == "__main__":
    unittest.main()

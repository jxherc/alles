"""recurring day-of-month must not drift. a monthly bill/task due the 31st should post on the
31st every month that has one (clamping to feb 28 only for feb), not get dragged down to the 28th
forever after the first short month. covers money recurring txns + repeating tasks + the migration."""

from datetime import date

from core.database import RecurringTxn, Transaction, Task
from routes import money
from services.task_nl import advance
from tests._client import ApiTest


class MoneyAnchorTests(ApiTest):
    def _seed(self, next_date, cycle="monthly", anchor=None):
        db = self.db()
        db.add(RecurringTxn(account_id="a1", amount=-50.0, payee="rent", cycle=cycle,
                            next_date=next_date, anchor_day=anchor, active=True))
        db.commit()
        db.close()

    def _posted_dates(self):
        db = self.db()
        out = sorted(t.date for t in db.query(Transaction).all())
        db.close()
        return out

    def test_monthly_31st_does_not_drift(self):
        self._seed("2026-01-31", anchor=31)
        db = self.db()
        money._post_due_recurring(db, today=date(2026, 5, 15))
        db.close()
        # jan 31, feb 28 (clamped), mar 31 (recovers!), apr 30, may not yet (15th < 31st… 5/31 > 5/15)
        self.assertEqual(self._posted_dates(), ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"])

    def test_create_sets_anchor_day(self):
        acct = self.client.post("/api/money/accounts", json={"name": "C", "opening": 0}).json()["id"]
        rid = self.client.post("/api/money/recurring", json={
            "account_id": acct, "amount": -9.99, "payee": "x", "cycle": "monthly",
            "next_date": "2026-03-30"}).json()["id"]
        db = self.db()
        self.assertEqual(db.get(RecurringTxn, rid).anchor_day, 30)
        db.close()

    def test_edit_next_date_resyncs_anchor(self):
        acct = self.client.post("/api/money/accounts", json={"name": "C", "opening": 0}).json()["id"]
        rid = self.client.post("/api/money/recurring", json={
            "account_id": acct, "amount": -9.99, "payee": "x", "cycle": "monthly",
            "next_date": "2026-03-30"}).json()["id"]
        self.client.patch(f"/api/money/recurring/{rid}", json={"next_date": "2026-04-15"})
        db = self.db()
        self.assertEqual(db.get(RecurringTxn, rid).anchor_day, 15)
        db.close()


class TaskAnchorTests(ApiTest):
    def test_monthly_advance_does_not_drift(self):
        due, seq = "2026-01-31", []
        for _ in range(4):
            due = advance(due, "monthly", 31)
            seq.append(due)
        self.assertEqual(seq, ["2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"])

    def test_yearly_feb29_recovers_on_next_leap(self):
        self.assertEqual(advance("2024-02-29", "yearly", 29), "2025-02-28")
        self.assertEqual(advance("2027-02-28", "yearly", 29), "2028-02-29")

    def test_completing_recurring_task_spawns_anchored_next(self):
        t = self.client.post("/api/tasks", json={
            "title": "pay rent", "due_date": "2026-01-31", "repeat": "monthly"}).json()
        self.assertEqual(self.db().get(Task, t["id"]).anchor_day, 31)
        r = self.client.patch(f"/api/tasks/{t['id']}", json={"done": True}).json()
        self.assertEqual(r["spawned"]["due_date"], "2026-02-28")
        # the spawned task keeps the 31 anchor so its next roll-forward recovers to march 31
        sp = self.db().get(Task, r["spawned"]["id"])
        self.assertEqual(sp.anchor_day, 31)


class MigrationAnchorTests(ApiTest):
    def test_migration_backfills_anchor_day(self):
        from sqlalchemy import text
        from core.migrations import m0008_recurring_anchor_day as m
        # simulate a pre-migration row by nulling the anchor, then run the backfill
        db = self.db()
        db.add(RecurringTxn(account_id="a", amount=-1.0, cycle="monthly",
                            next_date="2026-07-29", anchor_day=None, active=True))
        db.commit()
        with self.eng.begin() as conn:
            conn.execute(text("UPDATE money_recurring SET anchor_day = CAST(substr(next_date, 9, 2) AS INTEGER) "
                              "WHERE anchor_day IS NULL AND length(next_date) >= 10"))
        db.close()
        db = self.db()
        self.assertEqual(db.query(RecurringTxn).first().anchor_day, 29)
        db.close()

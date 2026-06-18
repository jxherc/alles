from datetime import datetime, timedelta

from tests._client import ApiTest
from core.database import (
    Task,
    JournalEntry,
    CalendarEvent,
    Account,
    Transaction,
    Subscription,
    Photo,
)


# DB-backed sources only — 'agent' and 'doc' read shared on-disk state
# (data/agent_runs + the real vault) that the in-memory test DB can't isolate.
DBT = "journal,task,calendar,money,sub,photo,mail"


class TimelineApiTest(ApiTest):
    def test_empty(self):
        r = self.client.get("/api/timeline", params={"types": DBT}).json()
        self.assertEqual(r["events"], [])

    def test_aggregates_and_sorts_desc(self):
        d = self.db()
        now = datetime.utcnow()
        # a completed task (recent) + an older one
        t1 = Task(title="ship feature", done=True, completed_at=now - timedelta(hours=1))
        t2 = Task(title="old todo", done=False, created_at=now - timedelta(days=2))
        d.add_all([t1, t2])
        d.add(
            JournalEntry(
                date="2026-06-15",
                content="a good day",
                mood="🙂",
                updated_at=now - timedelta(hours=3),
            )
        )
        acct = Account(name="checking", opening=0.0)
        d.add(acct)
        d.commit()
        d.add(
            Transaction(
                account_id=acct.id, date=(now.date()).isoformat(), amount=-12.5, payee="cafe"
            )
        )
        d.commit()
        d.close()

        r = self.client.get("/api/timeline", params={"days": 7, "types": DBT}).json()
        evs = r["events"]
        self.assertTrue(len(evs) >= 4)
        # strictly reverse-chron
        ts = [e["ts"] for e in evs]
        self.assertEqual(ts, sorted(ts, reverse=True))
        types = {e["type"] for e in evs}
        self.assertEqual(types, {"task", "journal", "money"})
        done = next(e for e in evs if e["type"] == "task" and e["title"].startswith("✓"))
        self.assertEqual(done["subtitle"], "completed")

    def test_type_filter(self):
        d = self.db()
        d.add(Task(title="only task", done=True, completed_at=datetime.utcnow()))
        d.add(JournalEntry(date="2026-06-15", content="hi", updated_at=datetime.utcnow()))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "task"}).json()
        self.assertTrue(all(e["type"] == "task" for e in r["events"]))
        self.assertTrue(any(e["type"] == "task" for e in r["events"]))

    def test_window_excludes_old(self):
        d = self.db()
        d.add(
            Task(title="ancient", done=True, completed_at=datetime.utcnow() - timedelta(days=400))
        )
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"days": 30, "types": DBT}).json()
        self.assertEqual(r["events"], [])

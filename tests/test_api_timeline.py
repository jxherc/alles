from datetime import datetime, timedelta

from core.database import (
    Account,
    CalendarEvent,
    JournalEntry,
    Task,
    Transaction,
)
from tests._client import ApiTest

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

    def test_response_has_types_field(self):
        r = self.client.get("/api/timeline", params={"types": "task,journal"}).json()
        self.assertIn("types", r)
        self.assertEqual(sorted(r["types"]), ["journal", "task"])

    def test_limit_param_caps_results(self):
        d = self.db()
        now = datetime.utcnow()
        for i in range(10):
            d.add(Task(title=f"task {i}", done=True, completed_at=now - timedelta(minutes=i)))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "task", "limit": 3}).json()
        self.assertLessEqual(len(r["events"]), 3)

    def test_text_filter_q_param(self):
        d = self.db()
        now = datetime.utcnow()
        d.add(Task(title="buy groceries", done=True, completed_at=now))
        d.add(Task(title="unrelated thing", done=True, completed_at=now))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "task", "q": "groceries"}).json()
        titles = [e["title"] for e in r["events"]]
        self.assertTrue(any("groceries" in t for t in titles))
        self.assertFalse(any("unrelated" in t for t in titles))

    def test_summary_endpoint_totals(self):
        d = self.db()
        now = datetime.utcnow()
        d.add(Task(title="t1", done=True, completed_at=now))
        d.add(Task(title="t2", done=True, completed_at=now - timedelta(hours=1)))
        d.add(JournalEntry(date="2026-06-18", content="hi", updated_at=now))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline/summary", params={"types": "task,journal"}).json()
        self.assertIn("total", r)
        self.assertIn("by_type", r)
        self.assertGreaterEqual(r["total"], 3)
        types_seen = {row["type"] for row in r["by_type"]}
        self.assertIn("task", types_seen)
        self.assertIn("journal", types_seen)

    def test_pending_task_shows_as_added(self):
        d = self.db()
        now = datetime.utcnow()
        d.add(Task(title="pending item", done=False, created_at=now))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "task", "days": 1}).json()
        evs = [e for e in r["events"] if "pending item" in e["title"]]
        self.assertTrue(len(evs) >= 1)
        self.assertEqual(evs[0]["subtitle"], "added")

    def test_calendar_event_in_window(self):
        d = self.db()
        now = datetime.utcnow()
        d.add(
            CalendarEvent(
                title="today standup",
                start_dt=(now - timedelta(hours=2)).isoformat(),
                end_dt=(now - timedelta(hours=1)).isoformat(),
            )
        )
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "calendar", "days": 2}).json()
        titles = [e["title"] for e in r["events"]]
        self.assertIn("today standup", titles)

"""stage 0c - event/mutation spine. tests first (RED)."""

import json
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import events


class SpineTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        events.clear_subscribers()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _events(self, kind=None):
        q = self.s.query(db.MutationEvent)
        if kind:
            q = q.filter(db.MutationEvent.entity_kind == kind)
        return q.order_by(db.MutationEvent.ts).all()

    def test_tracked_set_is_the_curated_eight(self):
        names = {m.__name__ for m in events.TRACKED}
        self.assertEqual(
            names,
            {
                "Task",
                "Transaction",
                "Subscription",
                "CalendarEvent",
                "Note",
                "JournalEntry",
                "Habit",
                "ProactiveItem",
            },
        )

    def test_insert_writes_mutation_event(self):
        t = db.Task(title="do it")
        self.s.add(t)
        self.s.commit()
        evs = self._events("tasks")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].op, "insert")
        self.assertEqual(evs[0].entity_id, t.id)
        self.assertEqual(evs[0].entity_kind, "tasks")

    def test_update_writes_changed_fields_only(self):
        t = db.Task(title="a")
        self.s.add(t)
        self.s.commit()
        t.title = "b"
        self.s.commit()
        ups = [e for e in self._events("tasks") if e.op == "update"]
        self.assertEqual(len(ups), 1)
        fields = json.loads(ups[0].fields)
        self.assertIn("title", fields)
        self.assertEqual(fields["title"], "b")
        self.assertNotIn("id", fields)  # unchanged columns not recorded

    def test_delete_writes_mutation_event(self):
        t = db.Task(title="a")
        self.s.add(t)
        self.s.commit()
        tid = t.id
        self.s.delete(t)
        self.s.commit()
        dels = [e for e in self._events("tasks") if e.op == "delete"]
        self.assertEqual(len(dels), 1)
        self.assertEqual(dels[0].entity_id, tid)

    def test_untracked_model_writes_nothing(self):
        ep = db.ModelEndpoint(name="x", base_url="http://x", api_key="")
        self.s.add(ep)
        self.s.commit()
        self.assertEqual(self._events("model_endpoints"), [])

    def test_rollback_writes_no_committed_event(self):
        t = db.Task(title="ghost")
        self.s.add(t)
        self.s.flush()  # listener writes the MutationEvent row IN this txn
        self.s.rollback()  # ... which rolls back with the txn
        self.assertEqual(self._events("tasks"), [])

    def test_multiple_mutations_one_txn(self):
        self.s.add_all([db.Task(title="a"), db.Task(title="b"), db.Habit(name="h")])
        self.s.commit()
        self.assertEqual(len(self._events("tasks")), 2)
        self.assertEqual(len(self._events("habits")), 1)

    def test_history_replays_in_order(self):
        t = db.Task(title="a")
        self.s.add(t)
        self.s.commit()
        t.title = "b"
        self.s.commit()
        t.title = "c"
        self.s.commit()
        hist = events.history(self.s, "tasks", t.id)
        self.assertEqual([e.op for e in hist], ["insert", "update", "update"])

    def test_subscriber_fires_after_commit(self):
        got = []
        events.subscribe(lambda muts: got.append(list(muts)))
        t = db.Task(title="a")
        self.s.add(t)
        self.s.commit()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0]["op"], "insert")
        self.assertEqual(got[0][0]["entity_kind"], "tasks")
        self.assertEqual(got[0][0]["entity_id"], t.id)

    def test_bad_subscriber_does_not_break_commit(self):
        def boom(muts):
            raise RuntimeError("subscriber blew up")

        events.subscribe(boom)
        t = db.Task(title="a")
        self.s.add(t)
        self.s.commit()  # must NOT raise
        self.assertEqual(len(self._events("tasks")), 1)  # the write still happened

    def test_record_mutation_manual_api(self):
        with self.eng.begin() as conn:
            events.record_mutation(conn, "custom_kind", "id1", "insert", {"x": 1})
        evs = self._events("custom_kind")
        self.assertEqual(len(evs), 1)
        self.assertEqual(json.loads(evs[0].fields)["x"], 1)


if __name__ == "__main__":
    unittest.main()

"""Recurring completion must preserve one successor through retries and correction."""

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.database import Task
from services.task_status import apply_status
from tests._client import ApiTest


class RecurrenceRecovery(ApiTest):
    def create(self):
        r = self.client.post(
            "/api/tasks",
            json={
                "title": "monthly review",
                "repeat": "monthly",
                "due_date": "2032-01-31",
                "notes": "keep notes",
                "project": "home",
                "tags": "one,two",
                "priority": 1,
            },
        )
        self.assertEqual(r.status_code, 200)
        return r.json()

    def change(self, tid, done):
        r = self.client.patch("/api/tasks/" + tid, json={"done": done})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_lost_reply_retry_and_month_anchor(self):
        t = self.create()
        first = self.change(t["id"], True)["spawned"]
        self.change(t["id"], True)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)
        self.assertEqual(first["due_date"], "2032-02-29")
        following = self.change(first["id"], True)["spawned"]
        self.assertEqual(following["due_date"], "2032-03-31")
        self.assertEqual(following["notes"], "keep notes")

    def test_complete_undo_redo_does_not_duplicate(self):
        t = self.create()
        first = self.change(t["id"], True)["spawned"]
        self.change(t["id"], False)
        self.change(t["id"], True)
        with self.db() as db:
            self.assertEqual({r.id for r in db.query(Task)}, {t["id"], first["id"]})

    def test_edited_successor_survives_without_a_duplicate(self):
        t = self.create()
        first = self.change(t["id"], True)["spawned"]
        self.assertEqual(
            self.client.patch(
                "/api/tasks/" + first["id"],
                json={"title": "edited future", "due_date": "2032-03-05", "notes": "changed"},
            ).status_code,
            200,
        )
        self.change(t["id"], False)
        self.change(t["id"], True)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)
            saved = db.get(Task, first["id"])
            self.assertEqual(
                (saved.title, saved.due_date, saved.notes),
                ("edited future", "2032-03-05", "changed"),
            )

    def test_deleted_successor_is_not_recreated(self):
        t = self.create()
        first = self.change(t["id"], True)["spawned"]
        self.assertEqual(self.client.delete("/api/tasks/" + first["id"]).status_code, 200)
        self.change(t["id"], False)
        self.change(t["id"], True)
        with self.db() as db:
            self.assertEqual([r.id for r in db.query(Task)], [t["id"]])

    def test_aide_correction_uses_same_recurrence_history(self):
        from services.agent_tools import _task_done

        t = self.create()
        for done in [True, False, True]:
            self.assertNotIn("error", asyncio.run(_task_done(t["id"], done)))
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)

    def test_two_stale_completions_do_not_spawn_twice(self):
        with tempfile.TemporaryDirectory(prefix="alles-recurrence-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'tasks.db'}")
            try:
                Task.__table__.create(engine)
                with Session(engine) as db:
                    t = Task(title="one", repeat="monthly", due_date="2032-01-31")
                    db.add(t)
                    db.commit()
                    tid = t.id
                barrier = threading.Barrier(2)

                def complete(_):
                    with Session(engine) as db:
                        t = db.get(Task, tid)
                        barrier.wait(timeout=5)
                        spawned = apply_status(db, t, done=True)
                        db.commit()
                        return spawned is not None

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(complete, [1, 2]))
                self.assertEqual(sum(results), 1)
                with Session(engine) as db:
                    self.assertEqual(db.query(Task).count(), 2)
            finally:
                engine.dispose()

    def test_failed_patch_rolls_back_issuance_and_successor(self):
        t = self.create()
        response = self.client.patch(
            "/api/tasks/" + t["id"], json={"done": True, "priority": "invalid"}
        )
        self.assertEqual(response.status_code, 400)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 1)
            saved = db.get(Task, t["id"])
            self.assertFalse(saved.done)
            self.assertFalse(saved.recurrence_issued)
        self.assertIn("spawned", self.change(t["id"], True))
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)

    def test_caller_rollback_preserves_future_completion(self):
        t = self.create()
        with self.db() as db:
            task = db.get(Task, t["id"])
            self.assertIsNotNone(apply_status(db, task, done=True))
            db.flush()
            db.rollback()
        with self.db() as db:
            self.assertFalse(db.get(Task, t["id"]).recurrence_issued)
            self.assertEqual(db.query(Task).count(), 1)
        self.assertIn("spawned", self.change(t["id"], True))

    def test_original_edits_do_not_issue_another_occurrence(self):
        t = self.create()
        next_task = self.change(t["id"], True)["spawned"]
        self.change(t["id"], False)
        self.assertEqual(
            self.client.patch(
                "/api/tasks/" + t["id"],
                json={"repeat": "weekly", "due_date": "2032-04-02", "title": "corrected original"},
            ).status_code,
            200,
        )
        self.assertNotIn("spawned", self.change(t["id"], True))
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)
            self.assertEqual(db.get(Task, next_task["id"]).due_date, "2032-02-29")

    def test_independent_identical_tasks_each_get_one_occurrence(self):
        one, two = self.create(), self.create()
        ids = {self.change(t["id"], True)["spawned"]["id"] for t in [one, two]}
        self.assertEqual(len(ids), 2)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 4)

    def test_new_completed_task_can_issue_on_its_first_eligible_transition(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "title": "created completed",
                "stage": "done",
                "repeat": "monthly",
                "due_date": "2032-01-31",
            },
        )
        self.assertEqual(response.status_code, 200)
        t = response.json()
        self.change(t["id"], False)
        self.assertIn("spawned", self.change(t["id"], True))
        self.change(t["id"], False)
        self.assertNotIn("spawned", self.change(t["id"], True))

    def test_nonrecurring_completion_does_not_consume_future_recurrence(self):
        response = self.client.post("/api/tasks", json={"title": "later recurring"})
        self.assertEqual(response.status_code, 200)
        tid = response.json()["id"]
        self.change(tid, True)
        self.change(tid, False)
        self.assertEqual(
            self.client.patch(
                "/api/tasks/" + tid, json={"repeat": "daily", "due_date": "2032-01-31"}
            ).status_code,
            200,
        )
        self.assertEqual(self.change(tid, True)["spawned"]["due_date"], "2032-02-01")

    def test_invalid_repeat_does_not_consume_future_occurrence(self):
        t = self.create()
        self.assertEqual(
            self.client.patch("/api/tasks/" + t["id"], json={"repeat": "invalid"}).status_code, 200
        )
        self.assertNotIn("spawned", self.change(t["id"], True))
        self.change(t["id"], False)
        self.assertEqual(
            self.client.patch("/api/tasks/" + t["id"], json={"repeat": "monthly"}).status_code, 200
        )
        self.assertIn("spawned", self.change(t["id"], True))

    def test_successor_retains_source_parent_and_new_issuance_state(self):
        t = self.create()
        with self.db() as db:
            original = db.get(Task, t["id"])
            original.parent_id = "owned-parent"
            original.source_json = '{"kind":"doc","id":"owned-source"}'
            db.commit()
        child = self.change(t["id"], True)["spawned"]
        with self.db() as db:
            original, next_task = db.get(Task, t["id"]), db.get(Task, child["id"])
            self.assertTrue(original.recurrence_issued)
            self.assertFalse(next_task.recurrence_issued)
            for field in [
                "title",
                "priority",
                "repeat",
                "tags",
                "project",
                "notes",
                "source_json",
                "parent_id",
            ]:
                self.assertEqual(getattr(original, field), getattr(next_task, field), field)
            self.assertEqual(next_task.anchor_day, 31)


class RecurrenceMigration(unittest.TestCase):
    def test_completed_legacy_recurring_rows_are_consumed_without_inferred_links(self):
        from sqlalchemy import text

        from core.migrations.m0061_task_recurrence_history import up

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, done BOOLEAN, repeat TEXT, due_date TEXT)"
                    )
                )
                for tid, done, repeat, due in [
                    ("completed", 1, "monthly", "2032-01-31"),
                    ("active", 0, "monthly", "2032-01-31"),
                    ("plain", 1, "", "2032-01-31"),
                    ("undated", 1, "monthly", None),
                ]:
                    conn.execute(
                        text("INSERT INTO tasks VALUES (:id,:title,:done,:repeat,:due)"),
                        {
                            "id": tid,
                            "title": "identical title",
                            "done": done,
                            "repeat": repeat,
                            "due": due,
                        },
                    )
                before = conn.execute(text("SELECT * FROM tasks ORDER BY id")).all()
                up(conn)
                self.assertEqual(
                    dict(conn.execute(text("SELECT id,recurrence_issued FROM tasks")).all()),
                    {"completed": 1, "active": 0, "plain": 0, "undated": 0},
                )
                self.assertEqual(
                    conn.execute(
                        text("SELECT id,title,done,repeat,due_date FROM tasks ORDER BY id")
                    ).all(),
                    before,
                )
                conn.execute(text("UPDATE tasks SET done = 1 WHERE id = 'active'"))
                up(conn)
                self.assertEqual(
                    conn.execute(
                        text("SELECT recurrence_issued FROM tasks WHERE id = 'active'")
                    ).scalar_one(),
                    0,
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

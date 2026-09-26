"""Conditional task patches use one SQLite write transaction, without a new schema."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, Task
from routes.tasks import update_task
from tests._client import ApiTest


class TaskConflictApiTests(ApiTest):
    def create(self, **fields):
        response = self.client.post(
            "/api/tasks",
            json={
                "title": "review 中文",
                "notes": "original",
                "project": "school",
                "due_date": "2032-11-06",
                **fields,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_disjoint_guarded_edit_preserves_saved_fields(self):
        task = self.create()
        url = "/api/tasks/" + task["id"]
        self.assertEqual(
            self.client.patch(
                url,
                json={
                    "notes": "new notes",
                    "due_date": "2032-11-07",
                    "expected": {"notes": "original", "due_date": "2032-11-06"},
                },
            ).status_code,
            200,
        )
        response = self.client.patch(
            url, json={"project": "university", "expected": {"project": "school"}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response.json()["notes"], response.json()["due_date"], response.json()["project"]),
            ("new notes", "2032-11-07", "university"),
        )

    def test_conflict_returns_current_values_without_any_partial_write(self):
        task = self.create()
        url = "/api/tasks/" + task["id"]
        self.client.patch(url, json={"notes": "new notes"})
        response = self.client.patch(
            url,
            json={
                "notes": "stale notes",
                "project": "college",
                "expected": {"notes": "original", "project": "school"},
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["fields"], ["notes"])
        self.assertEqual(response.json()["detail"]["current"]["notes"], "new notes")
        self.assertEqual(self.client.get("/api/tasks").json()[0]["project"], "school")
        self.assertEqual(
            self.client.patch(
                url, json={"project": "college", "expected": {"project": "school"}}
            ).status_code,
            200,
        )

    def test_invalid_expected_maps_never_write(self):
        task = self.create()
        url = "/api/tasks/" + task["id"]
        for body in (
            {"notes": "bad", "expected": None},
            {"notes": "bad", "expected": []},
            {"notes": "bad", "expected": {}},
            {"notes": "bad", "expected": {"notes": 1}},
            {"notes": "bad", "expected": {"notes": "original", "project": "school"}},
            {"unknown": "x", "expected": {"unknown": "x"}},
            {"priority": True, "expected": {"priority": 0}},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch(url, json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/tasks").json()[0]["notes"], "original")

    def test_conflict_does_not_complete_or_spawn_recurring_task(self):
        task = self.create(repeat="monthly")
        response = self.client.patch(
            "/api/tasks/" + task["id"],
            json={
                "done": True,
                "notes": "draft",
                "expected": {"done": False, "notes": "wrong original"},
            },
        )
        self.assertEqual(response.status_code, 409)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 1)
            row = db.get(Task, task["id"])
            self.assertFalse(row.done)
            self.assertIsNone(row.completed_at)
            self.assertEqual(row.due_date, "2032-11-06")

    def test_guarded_and_legacy_completion_keep_recurrence(self):
        for guarded in (False, True):
            task = self.create(repeat="monthly")
            body = {"done": True}
            if guarded:
                body["expected"] = {"done": False}
            response = self.client.patch("/api/tasks/" + task["id"], json=body)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["done"])
            self.assertEqual(response.json()["spawned"]["due_date"], "2032-12-06")

    def test_deleted_task_rejects_and_releases_transaction(self):
        self.assertEqual(
            self.client.patch(
                "/api/tasks/missing", json={"notes": "draft", "expected": {"notes": ""}}
            ).status_code,
            404,
        )
        self.create()

    def test_expected_values_use_editor_normalization(self):
        task = self.create(tags="planning, 家人", due_date=None)
        response = self.client.patch(
            "/api/tasks/" + task["id"],
            json={
                "tags": "planning, new",
                "due_date": "2032-11-07",
                "expected": {"tags": "planning,家人", "due_date": ""},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tags"], ["planning", "new"])

    def test_draft_scope_is_private_stable_and_rejects_another_owner(self):
        first = self.client.get("/api/tasks/draft-scope")
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(first.json(), self.client.get("/api/tasks/draft-scope").json())
        self.assertTrue(all(len(scope) == 64 for scope in first.json()["scopes"]))
        task = self.create()
        with patch("routes.tasks._draft_scopes", return_value=["other-owner"]):
            response = self.client.patch(
                "/api/tasks/" + task["id"],
                json={
                    "notes": "draft",
                    "expected": {"notes": "original"},
                    "draft_scope": first.json()["scopes"][0],
                },
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/tasks").json()[0]["notes"], "original")


class TaskSeparateSessionRaceTests(ApiTest):
    def race(self, bodies):
        # ApiTest's StaticPool is deliberately not used: each contender needs its
        # own connection and transaction against the same real SQLite file.
        with tempfile.TemporaryDirectory(prefix="alles-task-race-") as root:
            engine = create_engine(
                "sqlite:///" + str(Path(root) / "race.sqlite"),
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, autoflush=False)
            with sessions() as db:
                row = Task(title="race task", notes="original", project="school")
                db.add(row)
                db.commit()
                task_id = row.id
            barrier = threading.Barrier(2)
            session_ids = []

            def contender(body):
                with sessions() as db:
                    session_ids.append(id(db))
                    barrier.wait(timeout=5)
                    try:
                        return 200, update_task(task_id, body, db)
                    except HTTPException as error:
                        return error.status_code, error.detail

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(contender, bodies))
            self.assertEqual(len(set(session_ids)), 2)
            with sessions() as db:
                row = db.get(Task, task_id)
                final = {"notes": row.notes, "project": row.project}
            engine.dispose()
            return results, final

    def test_simultaneous_same_field_has_exactly_one_winner(self):
        results, final = self.race(
            [
                {"notes": "A", "expected": {"notes": "original"}},
                {"notes": "B", "expected": {"notes": "original"}},
            ]
        )
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        winner = next(body["notes"] for status, body in results if status == 200)
        conflict = next(body for status, body in results if status == 409)
        self.assertEqual(final["notes"], winner)
        self.assertEqual(conflict["current"]["notes"], winner)

    def test_simultaneous_disjoint_fields_both_survive(self):
        results, final = self.race(
            [
                {"notes": "A", "expected": {"notes": "original"}},
                {"project": "university", "expected": {"project": "school"}},
            ]
        )
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(final, {"notes": "A", "project": "university"})

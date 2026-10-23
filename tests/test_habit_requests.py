import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, Habit, HabitCreateReceipt
from core.migrations import m0051_habit_create_receipts
from routes.habits import HabitBody, create_habit
from tests._client import ApiTest


class HabitRecoveryTests(ApiTest):
    def body(self, **values):
        return {
            "name": "daily reading",
            "cadence": "daily",
            "target": 1,
            "request_id": str(uuid.uuid4()),
        } | values

    def create(self, body):
        return self.client.post("/api/habits", json=body)

    def test_retry_is_one_habit_and_new_identity_allows_intentional_repeat(self):
        body = self.body()
        first, second = self.create(body), self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        repeated = self.create(self.body())
        self.assertNotEqual(first.json()["id"], repeated.json()["id"])
        self.assertEqual(len(self.client.get("/api/habits/overview").json()["habits"]), 2)

    def test_changed_retry_requires_review_and_recovery_uses_current_values(self):
        body = self.body()
        saved = self.create(body).json()
        changed = self.create(body | {"name": "changed reading"})
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(
            self.client.patch(
                "/api/habits/" + saved["id"], json={"name": "owner correction"}
            ).status_code,
            200,
        )
        recovered = self.client.get("/api/habits/requests/" + body["request_id"])
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["name"], "owner correction")

    def test_deleted_habit_is_not_recreated_by_an_uncertain_retry(self):
        body = self.body()
        saved = self.create(body).json()
        self.assertEqual(self.client.delete("/api/habits/" + saved["id"]).status_code, 200)
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(
            self.client.get("/api/habits/requests/" + body["request_id"]).status_code, 410
        )
        self.assertEqual(self.client.get("/api/habits/overview").json()["habits"], [])

    def test_archived_habit_can_be_found_and_restored_with_its_history(self):
        saved = self.create(self.body()).json()
        day = date.today().isoformat()
        self.assertEqual(
            self.client.post(
                "/api/habits/" + saved["id"] + "/toggle", json={"date": day, "done": True}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch("/api/habits/" + saved["id"], json={"archived": True}).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/habits/overview").json()["habits"], [])
        archived = self.client.get("/api/habits/overview", params={"archived": True}).json()[
            "habits"
        ]
        self.assertEqual([row["id"] for row in archived], [saved["id"]])
        self.assertTrue(archived[0]["done_today"])
        self.assertEqual(
            self.client.patch("/api/habits/" + saved["id"], json={"archived": False}).status_code,
            200,
        )
        restored = self.client.get("/api/habits/overview").json()["habits"]
        self.assertEqual([row["id"] for row in restored], [saved["id"]])
        self.assertTrue(restored[0]["done_today"])

    def test_normalized_retry_and_archived_conflict(self):
        body = self.body(name=" read ", icon=" x ", color=" blue ", target=0)
        first = self.create(body).json()
        retry = self.create(body | {"name": "read", "icon": "x", "color": "blue", "target": 1})
        self.assertEqual(retry.json(), first)
        self.client.patch("/api/habits/" + first["id"], json={"archived": True})
        self.assertEqual(self.create(body).status_code, 409)
        self.assertTrue(
            self.client.get("/api/habits/requests/" + body["request_id"]).json()["archived"]
        )
        self.assertEqual(self.client.get("/api/habits/overview").json()["habits"], [])

    def test_legacy_repeats_invalid_and_missing_identity(self):
        body = self.body()
        body.pop("request_id")
        self.assertNotEqual(self.create(body).json()["id"], self.create(body).json()["id"])
        for identity in ["bad", uuid.uuid4().hex, str(uuid.uuid4()).upper()]:
            self.assertEqual(self.create(body | {"request_id": identity}).status_code, 400)
            self.assertEqual(self.client.get("/api/habits/requests/" + identity).status_code, 400)
        self.assertEqual(
            self.client.get("/api/habits/requests/" + str(uuid.uuid4())).status_code, 404
        )
        with self.db() as db:
            self.assertEqual(db.query(HabitCreateReceipt).count(), 0)
            self.assertEqual(db.query(Habit).count(), 2)

    def test_receipt_is_content_free_and_tombstoned_on_delete(self):
        body = self.body()
        saved = self.create(body).json()
        with self.db() as db:
            receipt = db.query(HabitCreateReceipt).one()
            self.assertEqual(receipt.habit_id, saved["id"])
            self.assertEqual(
                set(receipt.__table__.columns.keys()), {"id", "habit_id", "created_at"}
            )
        self.client.delete("/api/habits/" + saved["id"])
        with self.db() as db:
            self.assertIsNone(db.query(HabitCreateReceipt).one().habit_id)

    def test_failed_commit_rolls_back_habit_and_receipt(self):
        body = HabitBody(**self.body())
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    create_habit(body, db)
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(HabitCreateReceipt).count(), 0)
            self.assertEqual(db.query(Habit).count(), 0)
            saved = create_habit(body, db)
            self.assertEqual(db.query(HabitCreateReceipt).one().habit_id, saved["id"])

    def test_concurrent_connections_create_once_and_reopen_replays(self):
        with tempfile.TemporaryDirectory(prefix="alles-habit-request-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'habits.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            body, barrier = HabitBody(**self.body()), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=10)
                    return create_habit(body, db)["id"]

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    ids = [future.result(timeout=20) for future in futures]
                self.assertEqual(ids[0], ids[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(create_habit(body, db)["id"], ids[0])
                    self.assertEqual(db.query(Habit).count(), 1)
                    self.assertEqual(db.query(HabitCreateReceipt).count(), 1)
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_preserves_existing_rows(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE habits (id TEXT PRIMARY KEY, name TEXT)"))
                conn.execute(text("INSERT INTO habits VALUES ('old','reading')"))
                m0051_habit_create_receipts.up(conn)
                m0051_habit_create_receipts.up(conn)
                self.assertEqual(conn.execute(text("SELECT name FROM habits")).scalar(), "reading")
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM habit_create_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()

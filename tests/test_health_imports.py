import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, HealthEntry, HealthImportReceipt
from core.migrations import m0052_health_import_identity
from routes.health import KINDS
from services.health_imports import import_entries
from tests._client import ApiTest


class HealthImportRecoveryTests(ApiTest):
    def body(self):
        return {
            "text": "date,kind,value,unit\n2026-10-01,weight,74.25,kg\n2026-10-01,sleep,8,h\n",
            "request_id": str(uuid.uuid4()),
        }

    def test_repeated_import_identity_creates_one_batch(self):
        body = self.body()
        self.assertEqual(self.client.post("/api/health/import", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/health/import", json=body).status_code, 200)
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)

    def test_changed_retry_requires_explicit_new_import(self):
        body = self.body()
        self.client.post("/api/health/import", json=body)
        response = self.client.post(
            "/api/health/import", json=body | {"text": body["text"].replace("74.25", "75.25")}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)

    def test_invalid_date_is_not_silently_replaced_with_today(self):
        body = self.body()
        response = self.client.post(
            "/api/health/import",
            json=body | {"text": body["text"].replace("2026-10-01", "2026-02-30")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])

    def test_strict_import_rejects_bad_values_without_partial_writes(self):
        body = self.body()
        csv = body["text"] + "2026-10-01,weight,NaN,kg\n"
        rejected = self.client.post("/api/health/import", json=body | {"text": csv, "strict": True})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("line 4", rejected.json()["detail"])
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])
        with self.db() as db:
            self.assertEqual(db.query(HealthImportReceipt).count(), 0)
        accepted = self.client.post("/api/health/import", json=body | {"strict": True})
        self.assertEqual(accepted.json(), {"imported": 2, "skipped": 0, "replayed": False})

    def test_complete_supplied_dates_are_validated(self):
        for value in [
            "2026-10-011",
            "2026-10-01garbage",
            "2026-10-01T99:30:00",
            "2026-10-01T12:30:00garbage",
        ]:
            with self.subTest(value=value):
                before = self.client.get("/api/health").json()["entries"]
                body = self.body() | {
                    "text": f"date,kind,value,unit\n{value},weight,74.25,kg\n",
                    "strict": True,
                }
                response = self.client.post("/api/health/import", json=body)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.client.get("/api/health").json()["entries"], before)

    def test_strict_surplus_cells_reject_the_whole_batch(self):
        body = self.body() | {"strict": True}
        body["text"] += "2026-10-01,weight,74,25,kg\n"
        response = self.client.post("/api/health/import", json=body)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("line 4", response.json()["detail"])
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])
        with self.db() as db:
            self.assertEqual(db.query(HealthImportReceipt).count(), 0)

    def test_valid_full_dates_and_timestamps_keep_their_written_day(self):
        for value in [
            "2026-10-01",
            "20261001",
            "2026-10-01T23:45:30-05:00",
            "2026-10-01 04:30:00Z",
        ]:
            with self.subTest(value=value):
                body = self.body() | {
                    "text": f"date,kind,value,unit\n{value},weight,74.25,kg\n",
                    "strict": True,
                }
                response = self.client.post("/api/health/import", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(
                    all(
                        row["date"] == "2026-10-01"
                        for row in self.client.get("/api/health").json()["entries"]
                    )
                )

    def test_legacy_skip_counts_and_intentional_repeated_imports(self):
        csv = self.body()["text"] + "2026-10-01,weight,Infinity,kg\n"
        for _ in range(2):
            response = self.client.post("/api/health/import", json={"text": csv})
            self.assertEqual(response.json(), {"imported": 2, "skipped": 1, "replayed": False})
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 4)
        with self.db() as db:
            self.assertEqual(db.query(HealthImportReceipt).count(), 0)

    def test_replay_does_not_recreate_deleted_rows_and_new_request_is_explicit_repeat(self):
        body = self.body()
        self.client.post("/api/health/import", json=body)
        for row in self.client.get("/api/health").json()["entries"]:
            self.client.delete("/api/health/" + str(row["id"]))
        replay = self.client.post("/api/health/import", json=body)
        self.assertEqual(replay.json(), {"imported": 2, "skipped": 0, "replayed": True})
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])
        self.client.post("/api/health/import", json=body | {"request_id": str(uuid.uuid4())})
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)

    def test_bom_headers_and_unknown_metric_keep_their_values(self):
        body = self.body() | {
            "text": "\ufeffDate,Metric,Value,Unit\n20260102,steps,8000,count\n",
            "strict": True,
        }
        response = self.client.post("/api/health/import", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        row = self.client.get("/api/health").json()["entries"][0]
        self.assertEqual(
            (row["kind"], row["label"], row["date"], row["value"], row["unit"]),
            ("custom", "steps", "2026-01-02", 8000, "count"),
        )
        self.assertTrue(row["record_id"])

    def test_malformed_or_duplicate_headers_and_empty_strict_import_write_nothing(self):
        for csv in ["", "value,Value\n1,2\n", 'date,kind,value\n"unfinished']:
            with self.subTest(csv=csv):
                response = self.client.post(
                    "/api/health/import", json=self.body() | {"text": csv, "strict": True}
                )
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])

    def test_request_identity_and_validation_mode_are_bound(self):
        body = self.body()
        self.client.post("/api/health/import", json=body)
        self.assertEqual(
            self.client.post("/api/health/import", json=body | {"strict": True}).status_code, 409
        )
        for identity in ["invalid", uuid.uuid4().hex]:
            self.assertEqual(
                self.client.post(
                    "/api/health/import", json=body | {"request_id": identity}
                ).status_code,
                400,
            )
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)

    def test_commit_failure_rolls_back_rows_and_receipt(self):
        body = self.body()
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    import_entries(db, body["text"], kinds=KINDS, request_id=body["request_id"])
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(HealthEntry).count(), 0)
            self.assertEqual(db.query(HealthImportReceipt).count(), 0)
            self.assertEqual(
                import_entries(db, body["text"], kinds=KINDS, request_id=body["request_id"])[
                    "imported"
                ],
                2,
            )

    def test_concurrent_connections_commit_one_batch_and_reopen_replays(self):
        with tempfile.TemporaryDirectory(prefix="alles-health-import-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            body, barrier = self.body(), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=10)
                    return import_entries(
                        db, body["text"], kinds=KINDS, request_id=body["request_id"]
                    )

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = [pool.submit(save) for _ in range(2)]
                    results = [future.result(timeout=20) for future in results]
                self.assertEqual(sorted(row["replayed"] for row in results), [False, True])
                engine.dispose()
                with sessions() as db:
                    self.assertTrue(
                        import_entries(
                            db, body["text"], kinds=KINDS, request_id=body["request_id"]
                        )["replayed"]
                    )
                    self.assertEqual(db.query(HealthEntry).count(), 2)
                    self.assertEqual(db.query(HealthImportReceipt).count(), 1)
                    self.assertEqual(len({row.record_id for row in db.query(HealthEntry).all()}), 2)
            finally:
                engine.dispose()

    def test_migration_preserves_data_and_assigns_stable_distinct_identities(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE health_entries (id INTEGER PRIMARY KEY, value FLOAT)")
                )
                conn.execute(text("INSERT INTO health_entries VALUES (1,74.25),(2,74.25)"))
                m0052_health_import_identity.up(conn)
                first = conn.execute(
                    text("SELECT id,value,record_id FROM health_entries ORDER BY id")
                ).all()
                m0052_health_import_identity.up(conn)
                self.assertEqual(
                    conn.execute(
                        text("SELECT id,value,record_id FROM health_entries ORDER BY id")
                    ).all(),
                    first,
                )
                self.assertEqual([(row[0], row[1]) for row in first], [(1, 74.25), (2, 74.25)])
                self.assertEqual(len({str(uuid.UUID(row[2])) for row in first}), 2)
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM health_import_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()

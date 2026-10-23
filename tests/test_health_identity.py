import tempfile
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, HealthEntry
from routes.health import EntryPatch, delete_entry, update_entry
from services.health_entries import HealthInputError, save_entry
from tests._client import ApiTest


class HealthIdentityTests(ApiTest):
    def create(self, **fields):
        response = self.client.post(
            "/api/health", json={"kind": "weight", "value": 74.25, "unit": "kg"} | fields
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_records_have_stable_distinct_identity(self):
        original = self.create()
        self.assertTrue(original.get("record_id"))
        self.client.patch(
            "/api/health/" + str(original["id"]),
            json={"value": 73, "record_id": original["record_id"]},
        )
        self.assertEqual(
            self.client.get("/api/health").json()["entries"][0]["record_id"], original["record_id"]
        )
        self.client.delete("/api/health/" + str(original["id"]))
        replacement = self.create(kind="sleep", value=8, unit="h")
        self.assertEqual(replacement["id"], original["id"])
        self.assertNotEqual(replacement["record_id"], original["record_id"])

    def test_stale_delete_cannot_remove_reused_integer_id(self):
        original = self.create()
        endpoint = "/api/health/" + str(original["id"])
        self.client.delete(endpoint)
        replacement = self.create(kind="sleep", value=8, unit="h")
        self.assertEqual(replacement["id"], original["id"])
        result = self.client.delete(
            endpoint, params={"record_id": original.get("record_id", "previous-record")}
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [replacement])

    def test_stale_edit_cannot_change_reused_integer_id(self):
        original = self.create()
        endpoint = "/api/health/" + str(original["id"])
        self.client.delete(endpoint)
        replacement = self.create(kind="sleep", value=8, unit="h")
        result = self.client.patch(
            endpoint, json={"value": 99, "record_id": original.get("record_id", "previous-record")}
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [replacement])

    def test_conditional_writes_reject_replacement_created_after_read(self):
        for operation in ["edit", "delete"]:
            with (
                self.subTest(operation=operation),
                tempfile.TemporaryDirectory(prefix="alles-health-identity-") as root,
            ):
                engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
                with engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL"))
                Base.metadata.create_all(engine)
                sessions = sessionmaker(bind=engine)
                try:
                    with sessions() as db:
                        row = save_entry(db, kind="weight", value=74.25)
                        eid, original = row.id, row.record_id
                    replaced = []
                    with sessions() as db:

                        @event.listens_for(db, "loaded_as_persistent")
                        def replace(_session, row):
                            if not isinstance(row, HealthEntry) or replaced:
                                return
                            replaced.append(True)
                            with sessions() as other:
                                delete_entry(eid, other)
                                new = save_entry(other, kind="sleep", value=8)
                                self.assertEqual(new.id, eid)
                                self.assertNotEqual(new.record_id, original)

                        with self.assertRaises(HTTPException) as error:
                            if operation == "edit":
                                update_entry(eid, EntryPatch(value=99, record_id=original), db)
                            else:
                                delete_entry(eid, db, record_id=original)
                        self.assertEqual(error.exception.status_code, 410)
                    self.assertTrue(replaced)
                    with sessions() as db:
                        row = db.query(HealthEntry).one()
                        self.assertEqual((row.kind, row.value), ("sleep", 8))
                finally:
                    engine.dispose()

    def test_legacy_first_acknowledgment_cannot_return_replacement(self):
        with tempfile.TemporaryDirectory(prefix="alles-health-ack-identity-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                with sessions() as db:
                    commit = db.commit

                    def replace_after_commit():
                        eid = db.query(HealthEntry.id).one()[0]
                        commit()
                        with sessions() as other:
                            delete_entry(eid, other)
                            replacement = save_entry(other, kind="sleep", value=8)
                            self.assertEqual(replacement.id, eid)

                    with mock.patch.object(db, "commit", side_effect=replace_after_commit):
                        with self.assertRaises(HealthInputError) as error:
                            save_entry(db, kind="weight", value=74.25)
                        self.assertEqual(error.exception.status_code, 410)
                with sessions() as db:
                    self.assertEqual(db.query(HealthEntry).one().kind, "sleep")
            finally:
                engine.dispose()

    def test_legacy_calls_still_edit_and_delete_current_record(self):
        original = self.create()
        endpoint = "/api/health/" + str(original["id"])
        corrected = self.client.patch(endpoint, json={"value": 73})
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(corrected.json()["record_id"], original["record_id"])
        self.assertEqual(self.client.delete(endpoint).status_code, 200)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])

"""Reminder create recovery and UTC delivery boundaries on disposable records."""

import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, mock

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, ModelEndpoint, Reminder, ReminderCreateReceipt, Session
from core.migrations import m0054_reminder_create_receipts
from routes.reminders import ReminderCreate, acknowledge_reminder, create_reminder, delete_reminder
from tests._client import ApiTest


class ReminderRequestTests(ApiTest):
    def body(self, **changes):
        return {
            "text": "owned reminder fixture",
            "trigger_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "request_id": str(uuid.uuid4()),
        } | changes

    def create(self, body):
        return self.client.post("/api/reminders", json=body)

    def conversation(self, configured=True):
        with self.db() as db:
            endpoint = ModelEndpoint(
                name="fixture",
                base_url="https://model.example.invalid",
                cached_models='["fixture"]',
            )
            if configured:
                db.add(endpoint)
                db.flush()
            session = Session(
                name="reminder fixture",
                endpoint_id=endpoint.id if configured else None,
                model="fixture",
            )
            db.add(session)
            db.commit()
            return session.id

    def test_retry_returns_one_record_and_new_identity_allows_another(self):
        body = self.body()
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.create(body).json(), first.json())
        second = self.create(body | {"request_id": str(uuid.uuid4())})
        self.assertNotEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(len(self.client.get("/api/reminders").json()), 2)

    def test_changed_intent_conflicts_without_creating(self):
        body = self.body()
        self.create(body)
        for change in [
            {"text": "changed"},
            {"trigger_at": (datetime.now(UTC) + timedelta(days=3)).isoformat()},
        ]:
            self.assertEqual(self.create(body | change).status_code, 409)
        self.assertEqual(len(self.client.get("/api/reminders").json()), 1)

    def test_deleted_intent_cannot_return_or_recreate_a_reminder(self):
        body = self.body()
        first = self.create(body).json()
        self.assertEqual(self.client.delete("/api/reminders/" + first["id"]).status_code, 200)
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_fired_retry_reports_current_delivery_without_rescheduling(self):
        body = self.body(trigger_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
        first = self.create(body).json()
        self.assertEqual(
            self.client.post("/api/reminders/" + first["id"] + "/ack").status_code, 200
        )
        retry = self.create(body)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["id"], first["id"])
        self.assertTrue(retry.json()["fired"])
        self.assertEqual(self.client.get("/api/reminders/due").json(), [])
        with self.db() as db:
            self.assertEqual(db.query(Reminder).count(), 1)

    def test_invalid_identity_creates_nothing(self):
        self.assertEqual(self.create(self.body(request_id="invalid")).status_code, 400)
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_offset_timestamp_and_utc_timestamp_are_the_same_intent(self):
        instant = datetime.now(UTC) - timedelta(hours=1)
        local = instant.astimezone(timezone(timedelta(hours=9)))
        body = self.body(trigger_at=local.isoformat())
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["trigger_at"], instant.replace(tzinfo=None).isoformat())
        self.assertEqual(
            self.create(body | {"trigger_at": instant.isoformat()}).json()["id"], first.json()["id"]
        )
        self.assertIn(
            first.json()["id"], [r["id"] for r in self.client.get("/api/reminders/due").json()]
        )

    def test_legacy_naive_timestamp_still_means_utc(self):
        instant = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None)
        body = self.body(trigger_at=instant.isoformat())
        body.pop("request_id")
        first = self.create(body).json()
        second = self.create(body).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["trigger_at"], instant.isoformat())
        self.assertEqual(len(self.client.get("/api/reminders/due").json()), 2)

    def test_scheduled_message_requires_a_real_configured_conversation(self):
        for session_id in [None, "missing", self.conversation(configured=False)]:
            response = self.create(self.body(type="message", session_id=session_id))
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_valid_scheduled_message_stays_out_of_browser_toasts(self):
        body = self.body(
            type="message",
            session_id=self.conversation(),
            trigger_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        )
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.create(body).json()["id"], first.json()["id"])
        self.assertEqual(self.client.get("/api/reminders/due").json(), [])
        self.assertEqual(
            self.client.post("/api/reminders/" + first.json()["id"] + "/ack").status_code, 409
        )

    def test_empty_text_or_unknown_kind_does_not_create_an_undeliverable_record(self):
        for changes in [{"text": "  "}, {"type": "unsupported"}]:
            self.assertEqual(self.create(self.body(**changes)).status_code, 400)
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_receipt_contains_no_text_and_cancellation_tombstones_it(self):
        body = self.body()
        saved = self.create(body).json()
        with self.db() as db:
            receipt = db.query(ReminderCreateReceipt).one()
            self.assertEqual(receipt.reminder_id, saved["id"])
            self.assertEqual(
                set(receipt.__table__.columns.keys()), {"id", "reminder_id", "created_at"}
            )
        self.client.delete("/api/reminders/" + saved["id"])
        with self.db() as db:
            self.assertIsNone(db.query(ReminderCreateReceipt).one().reminder_id)

    def test_failed_commit_rolls_back_record_and_receipt(self):
        body = ReminderCreate(**self.body())
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    create_reminder(body, db)
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(ReminderCreateReceipt).count(), 0)
            self.assertEqual(db.query(Reminder).count(), 0)
            saved = create_reminder(body, db)
            self.assertEqual(db.query(ReminderCreateReceipt).one().reminder_id, saved["id"])

    def test_concurrent_connections_create_once_and_reopen_replays(self):
        with tempfile.TemporaryDirectory(prefix="alles-reminder-request-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'reminders.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            body, barrier = ReminderCreate(**self.body()), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=10)
                    return create_reminder(body, db)["id"]

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    ids = [future.result(timeout=20) for future in futures]
                self.assertEqual(ids[0], ids[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(create_reminder(body, db)["id"], ids[0])
                    self.assertEqual(db.query(Reminder).count(), 1)
                    self.assertEqual(db.query(ReminderCreateReceipt).count(), 1)
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_preserves_existing_reminders(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE reminders (id TEXT PRIMARY KEY, text TEXT)"))
                conn.execute(text("INSERT INTO reminders VALUES ('old','reading')"))
                m0054_reminder_create_receipts.up(conn)
                m0054_reminder_create_receipts.up(conn)
                self.assertEqual(
                    conn.execute(text("SELECT text FROM reminders")).scalar(), "reading"
                )
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM reminder_create_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()

    def test_message_accepts_an_inherited_aide_model_without_mutating_the_session(self):
        with self.db() as db:
            endpoint = ModelEndpoint(
                name="inherited", base_url="http://127.0.0.1:1/v1", cached_models='["fixture"]'
            )
            session = Session(name="inherited", model="")
            db.add_all([endpoint, session])
            db.commit()
            sid, eid = session.id, endpoint.id
        settings = {"model_roles": {"aide_chat": {"endpoint_id": eid, "model": "fixture"}}}
        with mock.patch("services.model_resolver.load_settings", return_value=settings):
            response = self.create(self.body(type="message", session_id=sid))
        self.assertEqual(response.status_code, 200, response.text)
        with self.db() as db:
            self.assertIsNone(db.get(Session, sid).endpoint_id)
            self.assertEqual(db.get(Session, sid).model, "")

    def test_started_message_cannot_claim_successful_cancellation(self):
        body = self.body(type="message", session_id=self.conversation())
        rid = self.create(body).json()["id"]
        with self.db() as db:
            db.get(Reminder, rid).notified = True
            db.commit()
        response = self.client.delete("/api/reminders/" + rid)
        self.assertEqual(response.status_code, 409)
        self.assertIn("already started", response.json()["detail"])
        rows = self.client.get("/api/reminders").json()
        self.assertEqual(rows[0]["id"], rid)
        self.assertTrue(rows[0]["delivery_started"])
        self.assertEqual(self.create(body).json()["id"], rid)
        with self.db() as db:
            db.get(Reminder, rid).fired = True
            db.commit()
        self.assertEqual(self.client.delete("/api/reminders/" + rid).status_code, 200)
        self.assertEqual(self.create(body).status_code, 410)


class ReminderReservationTests(TestCase):
    def test_response_releases_write_before_dependency_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="alles-reminder-reservation-") as root:
            engine = create_engine(
                f"sqlite:///{Path(root) / 'check.db'}", connect_args={"timeout": 0.1}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                for case in ["replay", "changed", "deleted", "missing-cancel", "not-due"]:
                    with self.subTest(case=case), sessions() as db:
                        body = ReminderCreate(
                            text="owned reservation fixture",
                            trigger_at="2032-06-10T05:30:00Z",
                            request_id=str(uuid.uuid4()),
                        )
                        rid = create_reminder(body, db)["id"]
                        if case == "deleted":
                            delete_reminder(rid, db)
                        try:
                            if case in ["replay", "deleted"]:
                                create_reminder(body, db)
                            elif case == "changed":
                                create_reminder(body.model_copy(update={"text": "changed"}), db)
                            elif case == "missing-cancel":
                                delete_reminder("missing", db)
                            else:
                                acknowledge_reminder(rid, db)
                        except HTTPException as error:
                            self.assertEqual(
                                error.status_code,
                                {
                                    "changed": 409,
                                    "deleted": 410,
                                    "missing-cancel": 404,
                                    "not-due": 409,
                                }[case],
                            )
                        with engine.begin() as other:
                            other.execute(
                                text("UPDATE reminders SET notified = notified WHERE id = :id"),
                                {"id": rid},
                            )
            finally:
                engine.dispose()

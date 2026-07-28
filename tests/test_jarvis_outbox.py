import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, JarvisConnector, JarvisDeliveryAttempt, JarvisRun, JarvisWorkflow
from core.migrations import (
    m0026_jarvis_records,
    m0027_jarvis_scheduler,
    m0028_delegated_actions,
    m0029_jarvis_outbox,
)
from services.jarvis_outbox import (
    _payload,
    claim_delivery,
    enqueue_delivery,
    process_outbox,
    reclaim_stale_deliveries,
    record_delivery_result,
    register_provider,
    unregister_provider,
)
from services.jarvis_store import append_event, create_run, transition_run
from tests._client import ApiTest


class JarvisOutboxTest(ApiTest):
    def _run(self, *, state="succeeded", summary="finished safely"):
        db = self.db()
        workflow = JarvisWorkflow(name="morning check", enabled=True)
        db.add(workflow)
        db.flush()
        run = create_run(db, workflow)
        if state != "queued":
            transition_run(db, run, "running")
            transition_run(db, run, state, result_summary=summary)
        db.commit()
        db.refresh(run)
        return db, run

    def test_enqueue_is_idempotent_and_keeps_run_success_separate(self):
        db, run = self._run()
        first, created = enqueue_delivery(db, run, channel="test", privacy_level="title_status")
        second, created_again = enqueue_delivery(
            db, run, channel="test", privacy_level="title_status"
        )
        db.commit()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(run.state, "succeeded")
        self.assertEqual(first.state, "pending")
        db.close()

    def test_event_must_belong_to_the_same_run(self):
        db, first = self._run()
        workflow = db.query(JarvisWorkflow).first()
        other = create_run(db, workflow)
        event_row = append_event(db, other, "result", summary="other")
        with self.assertRaisesRegex(ValueError, "delivery_event_mismatch"):
            enqueue_delivery(db, first, channel="test", event_id=event_row.id)
        db.rollback()
        db.close()

    def test_provider_receives_stable_key_and_only_selected_privacy(self):
        db, run = self._run(summary="private detailed result")
        delivery, _ = enqueue_delivery(
            db,
            run,
            channel="capture",
            privacy_level="title_status",
            idempotency_supported=True,
        )
        key = delivery.idempotency_key
        db.commit()
        delivery_id = delivery.id
        run_id = run.id
        db.close()
        seen = {}

        def provider(payload, *, idempotency_key, connector):
            seen.update(payload)
            seen["key"] = idempotency_key
            seen["connector"] = connector
            return {"classification": "delivered", "provider_message_id": "provider-1"}

        register_provider("capture", provider)
        try:
            result = asyncio.run(process_outbox())
        finally:
            unregister_provider("capture")
        self.assertEqual(result, {"delivered": 1, "failed": 0})
        self.assertEqual(seen["key"], key)
        self.assertEqual(seen["title"], "morning check")
        self.assertNotIn("summary", seen)
        self.assertIsNone(seen["connector"])
        db = self.db()
        saved = db.get(JarvisDeliveryAttempt, delivery_id)
        self.assertEqual(saved.state, "delivered")
        self.assertEqual(saved.provider_message_id, "provider-1")
        self.assertEqual(db.get(JarvisRun, run_id).state, "succeeded")
        db.close()

    def test_summary_privacy_uses_event_reference_after_restart(self):
        db, run = self._run()
        event_row = append_event(db, run, "result", summary="owner-approved short summary")
        delivery, _ = enqueue_delivery(
            db,
            run,
            channel="summary",
            privacy_level="summary",
            event_id=event_row.id,
        )
        delivery_id = delivery.id
        db.commit()
        db.close()
        payloads = []
        register_provider(
            "summary",
            lambda payload, **_kwargs: (
                payloads.append(payload)
                or {"classification": "delivered", "provider_message_id": "p2"}
            ),
        )
        try:
            asyncio.run(process_outbox())
        finally:
            unregister_provider("summary")
        self.assertEqual(payloads[0]["summary"], "owner-approved short summary")
        self.assertEqual(payloads[0]["context"], {})
        db = self.db()
        self.assertEqual(db.get(JarvisDeliveryAttempt, delivery_id).state, "delivered")
        db.close()

    def test_summary_context_exposes_only_channel_approved_fields(self):
        db, run = self._run()
        event_row = append_event(
            db,
            run,
            "discord_notice_queued",
            summary="owner-approved notice",
            data={
                "channel_id": "123",
                "streamed_message_id": "456",
                "notice_key": "internal-routing-key",
                "private_prompt": "never send this",
            },
        )
        delivery, _ = enqueue_delivery(
            db,
            run,
            channel="discord",
            privacy_level="summary",
            event_id=event_row.id,
        )
        db.flush()
        payload = _payload(db, delivery)
        db.rollback()
        db.close()
        self.assertEqual(
            payload["context"],
            {"channel_id": "123", "streamed_message_id": "456"},
        )

    def test_failure_classes_have_bounded_retry_rules(self):
        now = datetime(2026, 1, 2, 3)
        db, run = self._run()
        transient, _ = enqueue_delivery(db, run, channel="transient")
        permanent, _ = enqueue_delivery(db, run, channel="permanent")
        uncertain, _ = enqueue_delivery(db, run, channel="uncertain")
        db.commit()
        claimed = {}
        for worker in ("a", "b", "c"):
            row = claim_delivery(db, worker, now=now)
            claimed[row.channel] = row
        record_delivery_result(claimed["transient"], classification="transient", now=now)
        record_delivery_result(claimed["permanent"], classification="permanent", now=now)
        record_delivery_result(claimed["uncertain"], classification="uncertain", now=now)
        self.assertEqual(transient.state, "retry")
        self.assertEqual(transient.next_attempt_at, now + timedelta(seconds=10))
        self.assertEqual(permanent.state, "failed")
        self.assertEqual(uncertain.state, "uncertain")
        self.assertIsNone(claim_delivery(db, "early", now=now + timedelta(seconds=9)))
        db.rollback()
        db.close()

    def test_stale_delivery_retries_only_with_provider_idempotency(self):
        now = datetime(2026, 1, 2, 3)
        db, run = self._run()
        safe, _ = enqueue_delivery(db, run, channel="safe", idempotency_supported=True)
        unsafe, _ = enqueue_delivery(db, run, channel="unsafe", idempotency_supported=False)
        db.commit()
        for worker in ("a", "b"):
            row = claim_delivery(db, worker, now=now, lease_seconds=30)
            row.lease_expires_at = now - timedelta(seconds=1)
        db.commit()
        result = reclaim_stale_deliveries(db, now=now)
        db.commit()
        self.assertEqual(result, {"retried": 1, "uncertain": 1})
        self.assertEqual(safe.state, "retry")
        self.assertEqual(unsafe.state, "uncertain")
        db.close()

    def test_provider_exception_is_uncertain_and_never_automatically_retried(self):
        db, run = self._run()
        delivery, _ = enqueue_delivery(db, run, channel="throws")
        delivery_id = delivery.id
        db.commit()
        db.close()

        def provider(*_args, **_kwargs):
            raise TimeoutError("synthetic timeout")

        register_provider("throws", provider)
        try:
            result = asyncio.run(process_outbox())
        finally:
            unregister_provider("throws")
        self.assertEqual(result, {"delivered": 0, "failed": 1})
        db = self.db()
        saved = db.get(JarvisDeliveryAttempt, delivery_id)
        self.assertEqual(saved.state, "uncertain")
        self.assertIsNone(saved.next_attempt_at)
        db.close()

    def test_provider_exception_retries_when_stable_key_prevents_duplicates(self):
        db, run = self._run()
        delivery, _ = enqueue_delivery(db, run, channel="safe-throws", idempotency_supported=True)
        delivery_id = delivery.id
        db.commit()
        db.close()

        def provider(*_args, **_kwargs):
            raise TimeoutError("synthetic timeout")

        register_provider("safe-throws", provider)
        try:
            result = asyncio.run(process_outbox())
        finally:
            unregister_provider("safe-throws")
        self.assertEqual(result, {"delivered": 0, "failed": 0})
        db = self.db()
        saved = db.get(JarvisDeliveryAttempt, delivery_id)
        self.assertEqual(saved.state, "retry")
        self.assertEqual(saved.safe_error_class, "transient")
        self.assertIsNotNone(saved.next_attempt_at)
        db.close()

    def test_disabled_connector_secret_is_never_given_to_provider(self):
        db, run = self._run()
        connector = JarvisConnector(
            name="paused", kind="connector-test", secret="synthetic-secret", enabled=False
        )
        db.add(connector)
        db.flush()
        delivery, _ = enqueue_delivery(db, run, channel="connector-test", connector_id=connector.id)
        delivery_id = delivery.id
        db.commit()
        db.close()
        calls = []
        register_provider(
            "connector-test",
            lambda *_args, **_kwargs: calls.append(True) or {"classification": "delivered"},
        )
        try:
            asyncio.run(process_outbox())
        finally:
            unregister_provider("connector-test")
        self.assertEqual(calls, [])
        db = self.db()
        self.assertEqual(db.get(JarvisDeliveryAttempt, delivery_id).state, "failed")
        db.close()

    def test_api_never_allows_manual_retry_of_uncertain_delivery(self):
        db, run = self._run()
        delivery, _ = enqueue_delivery(db, run, channel="unknown")
        delivery.state = "uncertain"
        db.commit()
        delivery_id = delivery.id
        db.close()
        response = self.client.post(f"/api/jarvis/deliveries/{delivery_id}/retry")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "uncertain_delivery_not_retryable")

    def test_delivery_api_queues_once_and_lists_safe_fields(self):
        db, run = self._run()
        run_id = run.id
        db.close()
        first = self.client.post(
            f"/api/jarvis/runs/{run_id}/deliveries",
            json={"channel": "api", "privacy_level": "status"},
        )
        second = self.client.post(
            f"/api/jarvis/runs/{run_id}/deliveries",
            json={"channel": "api", "privacy_level": "status"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(self.client.get("/api/jarvis/deliveries").json(), [first.json()])


class JarvisOutboxRaceTest(unittest.TestCase):
    def test_two_workers_cannot_claim_one_delivery(self):
        with tempfile.TemporaryDirectory(prefix="alles-outbox-race-") as temp:
            engine = create_engine(
                f"sqlite:///{Path(temp) / 'race.db'}",
                connect_args={"timeout": 10, "check_same_thread": False},
            )

            @event.listens_for(engine, "connect")
            def _sqlite_settings(connection, _record):
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=10000")

            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            db = Session()
            workflow = JarvisWorkflow(name="race", enabled=True)
            db.add(workflow)
            db.flush()
            run = create_run(db, workflow)
            delivery, _ = enqueue_delivery(db, run, channel="race")
            db.commit()
            delivery_id = delivery.id
            db.close()
            barrier = threading.Barrier(2)
            claimed = []

            def worker(name):
                session = Session()
                barrier.wait()
                row = claim_delivery(session, name, now=datetime(2026, 1, 2, 3))
                session.commit()
                claimed.append(row.id if row else None)
                session.close()

            threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(15)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(claimed.count(delivery_id), 1)
            self.assertEqual(claimed.count(None), 1)
            engine.dispose()


class JarvisOutboxMigrationTest(unittest.TestCase):
    def test_outbox_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="alles-outbox-schema-") as temp:
            engine = create_engine(f"sqlite:///{Path(temp) / 'old.db'}")
            with engine.begin() as conn:
                m0026_jarvis_records.up(conn)
                m0027_jarvis_scheduler.up(conn)
                m0028_delegated_actions.up(conn)
                m0029_jarvis_outbox.up(conn)
                m0029_jarvis_outbox.up(conn)
                columns = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(jarvis_delivery_attempts)"))
                }
                indexes = {
                    row["name"] for row in inspect(conn).get_indexes("jarvis_delivery_attempts")
                }
            engine.dispose()
        self.assertTrue(
            {
                "connector_id",
                "lease_owner",
                "lease_expires_at",
                "idempotency_supported",
                "last_attempt_at",
            }.issubset(columns)
        )
        self.assertIn("ix_jarvis_delivery_attempts_lease_expires_at", indexes)

import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, JarvisRun, JarvisTrigger, JarvisWorkflow
from core.migrations import m0026_jarvis_records, m0027_jarvis_scheduler
from services.jarvis_scheduler import (
    claim_next,
    complete_run,
    enqueue_occurrence,
    next_daily_occurrence,
    reclaim_stale_leases,
    record_failure,
    register_heartbeat_probe,
    renew_lease,
    scan_due,
    unregister_heartbeat_probe,
    validate_trigger_config,
)
from services.jarvis_store import append_event, create_run, transition_run
from tests._client import ApiTest


class JarvisScheduleMathTest(unittest.TestCase):
    def test_daily_schedule_skips_missing_dst_time(self):
        result = next_daily_occurrence(datetime(2024, 3, 10, 5), "02:30", "America/New_York")
        self.assertEqual(result, datetime(2024, 3, 11, 6, 30))

    def test_daily_schedule_uses_first_ambiguous_dst_time(self):
        result = next_daily_occurrence(datetime(2024, 11, 3, 4), "01:30", "America/New_York")
        self.assertEqual(result, datetime(2024, 11, 3, 5, 30))

    def test_trigger_and_policy_validation_fails_closed(self):
        invalid = [
            ("schedule", {"time": "25:00"}, "UTC", "invalid_schedule_time"),
            ("schedule", {"time": "09:00", "weekdays": [7]}, "UTC", "weekdays"),
            ("interval", {"every_seconds": 2}, "UTC", "interval"),
            ("interval", {"every_seconds": 30}, "Not/AZone", "timezone"),
            ("heartbeat", {"every_seconds": 30, "skip_when_busy": "yes"}, "UTC", "policy"),
            ("heartbeat", {"every_seconds": 30, "cost_limit": -1}, "UTC", "cost_limit"),
            (
                "heartbeat",
                {"every_seconds": 30, "quiet_hours": {"start": "22:00"}},
                "UTC",
                "quiet_hours",
            ),
        ]
        for kind, config, timezone_name, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_trigger_config(kind, config, timezone_name)
        validate_trigger_config(
            "heartbeat",
            {
                "every_seconds": 30,
                "quiet_hours": {"start": "22:00", "end": "07:00"},
                "skip_when_busy": True,
                "cost_limit": 0.25,
                "only_notify_when_useful": True,
            },
            "Asia/Taipei",
        )


class JarvisSchedulerTest(ApiTest):
    def _workflow(self, mode="one"):
        db = self.db()
        workflow = JarvisWorkflow(name="scheduled", enabled=True, concurrency_mode=mode)
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        return db, workflow

    def test_occurrence_is_idempotent(self):
        db, workflow = self._workflow()
        trigger = JarvisTrigger(
            workflow_id=workflow.id,
            kind="interval",
            config='{"every_seconds":30}',
            enabled=True,
        )
        db.add(trigger)
        db.flush()
        when = datetime(2026, 1, 2, 3, 4, 5)
        first, created = enqueue_occurrence(db, trigger, when)
        second, created_again = enqueue_occurrence(db, trigger, when)
        db.commit()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(db.query(JarvisRun).count(), 1)
        db.close()

    def test_default_concurrency_queues_but_parallel_claims_both(self):
        now = datetime(2026, 1, 2, 3)
        db, workflow = self._workflow()
        create_run(db, workflow, scheduled_for=now)
        create_run(db, workflow, scheduled_for=now + timedelta(seconds=1))
        db.commit()
        first = claim_next(db, "worker-a", now=now)
        self.assertIsNotNone(first)
        self.assertIsNone(claim_next(db, "worker-b", now=now))
        complete_run(db, first, "worker-a")
        self.assertIsNotNone(claim_next(db, "worker-b", now=now))
        db.rollback()
        db.close()

        db, workflow = self._workflow("parallel")
        create_run(db, workflow, scheduled_for=now)
        create_run(db, workflow, scheduled_for=now + timedelta(seconds=1))
        db.commit()
        self.assertIsNotNone(claim_next(db, "worker-a", now=now))
        self.assertIsNotNone(claim_next(db, "worker-b", now=now))
        db.rollback()
        db.close()

    def test_skip_mode_records_busy_occurrence_as_cancelled(self):
        db, workflow = self._workflow("skip")
        active = create_run(db, workflow)
        transition_run(db, active, "running")
        workflow.active_run_id = active.id
        trigger = JarvisTrigger(
            workflow_id=workflow.id,
            kind="interval",
            config='{"every_seconds":30}',
            enabled=True,
        )
        db.add(trigger)
        db.flush()
        run, created = enqueue_occurrence(db, trigger, datetime(2026, 1, 2, 3))
        db.commit()
        self.assertTrue(created)
        self.assertEqual(run.state, "cancelled")
        self.assertEqual(run.failure_class, "busy")
        db.close()

    def test_stale_lease_requeues_safe_run_and_marks_unknown_effect_uncertain(self):
        now = datetime(2026, 1, 2, 3)
        db, workflow = self._workflow("parallel")
        safe = create_run(db, workflow)
        unknown = create_run(db, workflow)
        for index, run in enumerate((safe, unknown)):
            transition_run(db, run, "running")
            run.lease_owner = f"dead-{index}"
            run.lease_expires_at = now - timedelta(seconds=1)
        append_event(db, unknown, "side_effect_started", summary="outside call started")
        db.commit()
        result = reclaim_stale_leases(db, now=now)
        db.commit()
        self.assertEqual(result, {"reclaimed": 1, "uncertain": 1})
        self.assertEqual(safe.state, "queued")
        self.assertEqual(unknown.state, "uncertain")
        for run in (safe, unknown):
            self.assertEqual(run.lease_owner, "")
            self.assertIsNone(run.lease_expires_at)
        db.close()

    def test_only_the_claiming_worker_can_renew_a_lease(self):
        now = datetime(2026, 1, 2, 3)
        db, workflow = self._workflow()
        create_run(db, workflow)
        db.commit()
        run = claim_next(db, "owner", now=now, lease_seconds=30)
        self.assertFalse(renew_lease(db, run.id, "other", now=now, lease_seconds=60))
        self.assertTrue(renew_lease(db, run.id, "owner", now=now, lease_seconds=60))
        db.expire(run)
        self.assertEqual(run.lease_expires_at, now + timedelta(seconds=60))
        with self.assertRaisesRegex(ValueError, "invalid_lease"):
            renew_lease(db, run.id, "owner", lease_seconds=2)
        db.rollback()
        db.close()

    def test_failure_classes_have_separate_retry_rules(self):
        now = datetime(2026, 1, 2, 3)
        db, workflow = self._workflow("parallel")
        transient = create_run(db, workflow)
        permanent = create_run(db, workflow)
        uncertain = create_run(db, workflow)
        db.commit()
        claimed_runs = {}
        for run, worker in ((transient, "a"), (permanent, "b"), (uncertain, "c")):
            claimed = claim_next(db, worker, now=now)
            self.assertEqual(claimed.id, run.id)
            claimed_runs[worker] = claimed
        transient = claimed_runs["a"]
        permanent = claimed_runs["b"]
        uncertain = claimed_runs["c"]
        record_failure(db, transient, "a", "transient", "try later", now=now)
        record_failure(db, permanent, "b", "permanent", "bad request", now=now)
        record_failure(db, uncertain, "c", "uncertain", "unknown result", now=now)
        self.assertEqual(transient.state, "queued")
        self.assertEqual(transient.next_attempt_at, now + timedelta(seconds=5))
        self.assertEqual(permanent.state, "failed")
        self.assertEqual(uncertain.state, "uncertain")
        self.assertIsNone(claim_next(db, "early", now=now + timedelta(seconds=4)))
        claimed = claim_next(db, "retry", now=now + timedelta(seconds=5))
        record_failure(
            db, claimed, "retry", "transient", "still unavailable", now=now, max_attempts=2
        )
        self.assertEqual(transient.state, "failed")
        self.assertEqual(transient.failure_class, "transient")
        db.rollback()
        db.close()

    def test_due_repeating_schedule_coalesces_and_missed_once_is_recorded(self):
        now = datetime(2026, 1, 2, 12)
        db, workflow = self._workflow("parallel")
        interval = JarvisTrigger(
            workflow_id=workflow.id,
            kind="interval",
            config='{"every_seconds":30}',
            enabled=True,
            next_run_at=now - timedelta(hours=4),
        )
        once = JarvisTrigger(
            workflow_id=workflow.id,
            kind="once",
            config='{"at":"2026-01-02T08:00:00","grace_seconds":60}',
            enabled=True,
            next_run_at=now - timedelta(hours=4),
        )
        db.add_all([interval, once])
        db.commit()
        interval_id = interval.id
        once_id = once.id
        db.close()
        result = asyncio.run(scan_due(now))
        self.assertEqual(result, {"created": 1, "missed": 1, "unchanged": 0})
        db = self.db()
        runs = db.query(JarvisRun).order_by(JarvisRun.created_at).all()
        self.assertEqual(len(runs), 2)
        self.assertEqual({run.state for run in runs}, {"queued", "cancelled"})
        self.assertGreater(db.get(JarvisTrigger, interval_id).next_run_at, now)
        self.assertFalse(db.get(JarvisTrigger, once_id).enabled)
        db.close()

    def test_heartbeat_uses_fingerprint_before_creating_work(self):
        now = datetime(2026, 1, 2, 12)
        db, workflow = self._workflow("parallel")
        trigger = JarvisTrigger(
            workflow_id=workflow.id,
            kind="heartbeat",
            config='{"every_seconds":30}',
            enabled=True,
            next_run_at=now,
        )
        db.add(trigger)
        db.commit()
        trigger_id = trigger.id
        db.close()

        values = iter(["first", "first", "changed"])
        register_heartbeat_probe(trigger_id, lambda: next(values))
        try:
            first = asyncio.run(scan_due(now))
            second = asyncio.run(scan_due(now + timedelta(seconds=30)))
            third = asyncio.run(scan_due(now + timedelta(seconds=60)))
        finally:
            unregister_heartbeat_probe(trigger_id)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(third["created"], 1)
        db = self.db()
        self.assertEqual(db.query(JarvisRun).count(), 2)
        self.assertEqual(db.get(JarvisTrigger, trigger_id).fingerprint, "changed")
        db.close()

    def test_trigger_api_validates_and_only_enables_after_review(self):
        workflow = self.client.post("/api/jarvis/workflows", json={"name": "api"}).json()
        invalid = self.client.post(
            f"/api/jarvis/workflows/{workflow['id']}/triggers",
            json={"kind": "schedule", "config": {"time": "nope"}},
        )
        self.assertEqual(invalid.status_code, 400)
        trigger = self.client.post(
            f"/api/jarvis/workflows/{workflow['id']}/triggers",
            json={"kind": "schedule", "config": {"time": "09:00"}, "timezone": "Asia/Taipei"},
        ).json()
        self.assertFalse(trigger["enabled"])
        enabled = self.client.patch(f"/api/jarvis/triggers/{trigger['id']}", json={"enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(enabled.json()["enabled"])
        self.assertIsNotNone(enabled.json()["next_run_at"])


class JarvisSchedulerRaceTest(unittest.TestCase):
    def test_two_workers_cannot_claim_the_same_run(self):
        with tempfile.TemporaryDirectory(prefix="alles-jarvis-race-") as temp:
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
            run = create_run(db, workflow, scheduled_for=datetime(2026, 1, 2, 3))
            db.commit()
            run_id = run.id
            db.close()

            barrier = threading.Barrier(2)
            claimed = []

            def worker(name):
                session = Session()
                barrier.wait()
                result = claim_next(session, name, now=datetime(2026, 1, 2, 3))
                session.commit()
                claimed.append(result.id if result else None)
                session.close()

            threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(15)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(claimed.count(run_id), 1)
            self.assertEqual(claimed.count(None), 1)
            engine.dispose()


class JarvisSchedulerMigrationTest(unittest.TestCase):
    def test_scheduler_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="alles-jarvis-scheduler-schema-") as temp:
            engine = create_engine(f"sqlite:///{Path(temp) / 'old.db'}")
            with engine.begin() as conn:
                m0026_jarvis_records.up(conn)
                m0027_jarvis_scheduler.up(conn)
                m0027_jarvis_scheduler.up(conn)
                workflow_columns = {
                    row[1] for row in conn.execute(text("PRAGMA table_info(jarvis_workflows)"))
                }
                run_columns = {
                    row[1] for row in conn.execute(text("PRAGMA table_info(jarvis_runs)"))
                }
                indexes = {item["name"] for item in inspect(conn).get_indexes("jarvis_runs")}
            engine.dispose()
        self.assertIn("active_run_id", workflow_columns)
        self.assertIn("next_attempt_at", run_columns)
        self.assertIn("ux_jarvis_runs_trigger_occurrence", indexes)

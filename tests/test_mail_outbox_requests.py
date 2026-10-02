"""Delivery intent retries use owned records and synthetic delivery only."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, MailAccount, ScheduledMail
from routes.mail import ScheduleBody, UndoableBody, cancel_scheduled, schedule_send, send_undoable
from tests._client import ApiTest


class OutboxRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        response = self.client.post(
            "/api/mail/accounts",
            json={
                "name": "Owned outbox",
                "email": "owned@example.invalid",
                "imap_host": "127.0.0.1",
                "imap_port": 9,
                "smtp_host": "127.0.0.1",
                "smtp_port": 9,
                "username": "owned",
                "password": "",
                "use_ssl": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.aid = response.json()["id"]

    def body(self, **changes):
        return (
            dict(
                to="recipient@example.invalid",
                cc="copy@example.invalid",
                bcc="private@example.invalid",
                subject="  exact 中文  ",
                body="plain\r\nbody ",
                html="<p>exact <b>rich</b> body 中文</p>\r\n",
                in_reply_to="<message@example.invalid>",
                references="<parent@example.invalid> <message@example.invalid>",
                request_id=str(uuid4()),
                send_at="2099-01-01T09:00:00-05:00",
            )
            | changes
        )

    def queue(self, body, kind="schedule", aid=None):
        return self.client.post("/api/mail/" + kind + "/" + (aid or self.aid), json=body)

    def current(self, identity, **params):
        return self.client.get("/api/mail/scheduled", params={"request_id": identity, **params})

    def test_schedule_exact_replay_and_intentional_repeat(self):
        body = self.body()
        first = self.queue(body).json()
        self.assertEqual(first["id"], body["request_id"])
        self.assertEqual(first["request_kind"], "schedule")
        self.assertIsNone(first["request_delay"])
        self.assertEqual(first["send_at"], "2099-01-01T14:00:00")
        for field in ["to", "cc", "bcc", "subject", "body", "html", "in_reply_to", "references"]:
            self.assertEqual(first[field], body[field])
        self.assertEqual(self.queue(body).json(), first)
        second = self.queue(body | {"request_id": str(uuid4())}).json()
        self.assertNotEqual(first["id"], second["id"])
        with self.db() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 2)

    def test_undo_retry_keeps_original_instant_and_delay(self):
        body = self.body(delay=3600)
        first = self.queue(body, "send-undoable").json()
        self.assertEqual(first["id"], body["request_id"])
        self.assertEqual(first["request_kind"], "send")
        self.assertEqual(first["request_delay"], 3600)
        self.assertEqual(self.queue(body, "send-undoable").json(), first)
        self.assertEqual(self.queue(body | {"delay": 3601}, "send-undoable").status_code, 409)
        self.assertEqual(self.current(first["id"]).json()["scheduled"], [first])

    def test_retry_terminal_states_never_requeues_or_hides_outcome(self):
        for kind in ["schedule", "send-undoable"]:
            for state in ["sending", "sent", "uncertain", "canceled"]:
                with self.subTest(kind=kind, state=state):
                    body = self.body(delay=3600)
                    first = self.queue(body, kind).json()
                    with self.db() as db:
                        db.get(ScheduledMail, first["id"]).status = state
                        db.commit()
                    replay = self.queue(body, kind)
                    self.assertEqual(replay.status_code, 200)
                    self.assertEqual(replay.json()["id"], first["id"])
                    self.assertEqual(replay.json()["status"], state)
                    self.assertEqual(replay.json()["send_at"], first["send_at"])
                    self.assertEqual(self.current(first["id"]).json()["scheduled"], [replay.json()])

    def test_original_delay_is_retained_even_when_delivery_uses_the_legacy_minimum(self):
        from datetime import UTC, datetime

        for delay in [0, -1]:
            with self.subTest(delay=delay):
                body = self.body(delay=delay)
                before = datetime.now(UTC).replace(tzinfo=None)
                first = self.queue(body, "send-undoable")
                self.assertEqual(first.status_code, 200)
                row = first.json()
                self.assertEqual(row["request_delay"], delay)
                self.assertGreaterEqual(
                    (datetime.fromisoformat(row["send_at"]) - before).total_seconds(), 1
                )
                self.assertEqual(self.queue(body, "send-undoable").json(), row)
                for changed in [delay - 1, delay + 1, 1]:
                    self.assertEqual(
                        self.queue(body | {"delay": changed}, "send-undoable").status_code, 409
                    )

    def test_changed_fields_account_kind_and_time_conflict(self):
        body = self.body()
        first = self.queue(body).json()
        for field in [
            "to",
            "cc",
            "bcc",
            "subject",
            "body",
            "html",
            "in_reply_to",
            "references",
            "send_at",
        ]:
            with self.subTest(field=field):
                changed = "2099-01-02T09:00:00-05:00" if field == "send_at" else "changed"
                self.assertEqual(self.queue(body | {field: changed}).status_code, 409)
        self.assertEqual(self.queue(body, aid="another-account").status_code, 409)
        self.assertEqual(self.queue(body, "send-undoable").status_code, 409)
        self.assertEqual(self.current(first["id"]).json()["scheduled"], [first])

    def test_replay_after_account_removal_reads_accepted_outcome(self):
        body = self.body()
        first = self.queue(body).json()
        self.assertEqual(self.client.delete("/api/mail/accounts/" + self.aid).status_code, 200)
        self.assertEqual(self.queue(body).json(), first)
        self.assertEqual(self.queue(body | {"request_id": str(uuid4())}).status_code, 404)

    def test_bad_times_and_identities_create_nothing(self):
        for value in [
            "",
            "2099-01-01",
            "2099-02-30T12:00",
            "2099-01-01T29:99",
            "2099-01-01T09:00+25:00",
            "2099-01-01T09:00+01:60",
        ]:
            with self.subTest(time=value):
                self.assertEqual(self.queue(self.body(send_at=value)).status_code, 400)
        for value in ["bad", "12345678-1234-4ABC-9abc-1234567890ab"]:
            with self.subTest(identity=value):
                self.assertEqual(self.queue(self.body(request_id=value)).status_code, 400)
        self.assertEqual(self.queue(self.body(delay=10**30), "send-undoable").status_code, 400)
        self.assertEqual(self.queue(self.body(delay=-(10**30)), "send-undoable").status_code, 400)
        with self.db() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 0)

    def test_naive_utc_and_offset_inputs_normalize_without_rewriting_old_rows(self):
        values = {
            "2099-01-01T09:00": "2099-01-01T09:00:00",
            "2099-01-01T09:00:00Z": "2099-01-01T09:00:00",
            "2099-01-01T09:00:00+14:00": "2098-12-31T19:00:00",
            "2099-01-01T09:00:00.123456+01:00": "2099-01-01T08:00:00.123456",
        }
        for source, expected in values.items():
            self.assertEqual(self.queue(self.body(send_at=source)).json()["send_at"], expected)

    def test_legacy_requests_stay_distinct_and_default_list_hides_terminal_rows(self):
        body = self.body(request_id="")
        a = self.queue(body).json()
        b = self.queue(body).json()
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["request_kind"], "")
        self.assertIsNone(a["request_delay"])
        self.assertEqual(self.queue(body | {"request_id": a["id"]}).status_code, 409)
        self.assertEqual(
            self.client.post("/api/mail/scheduled/" + a["id"] + "/cancel").status_code, 200
        )
        default = self.client.get("/api/mail/scheduled").json()
        self.assertNotIn("recovery_scopes", default)
        self.assertEqual([r["id"] for r in default["scheduled"]], [b["id"]])
        self.assertEqual(self.current(a["id"]).json()["scheduled"][0]["status"], "canceled")

    def test_context_scope_protects_creation_lookup_and_cancellation(self):
        info = self.client.get("/api/mail/scheduled?context=true").json()
        scope = info["recovery_scopes"][0]
        self.assertNotEqual(
            scope, self.client.get("/api/mail/drafts?context=true").json()["recovery_scopes"][0]
        )
        body = self.body(recovery_scope=scope)
        first = self.queue(body).json()
        foreign = "f" * 64
        self.assertEqual(self.queue(body | {"recovery_scope": foreign}).status_code, 403)
        self.assertEqual(self.current(first["id"], recovery_scope=foreign).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/mail/scheduled/" + first["id"] + "/cancel", params={"recovery_scope": foreign}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.current(first["id"], recovery_scope=scope).json()["scheduled"], [first]
        )

    def test_retained_key_rotation_keeps_pending_intents_and_cancellation_valid(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="old-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture"}),
        ):
            scope = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"][0]
            body = self.body(recovery_scope=scope)
            first = self.queue(body).json()
        with (
            mock.patch("services.secretstore.active_key_id", return_value="new-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"new-fixture", "old-fixture"}),
        ):
            scopes = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"]
            self.assertNotEqual(scope, scopes[0])
            self.assertIn(scope, scopes)
            self.assertEqual(self.queue(body).json(), first)
            self.assertEqual(
                self.current(first["id"], recovery_scope=scope).json()["scheduled"], [first]
            )
            response = self.client.post(
                "/api/mail/scheduled/" + first["id"] + "/cancel", params={"recovery_scope": scope}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.queue(body).json()["status"], "canceled")

    def test_cancel_replay_and_terminal_rejection(self):
        body = self.body()
        first = self.queue(body).json()
        url = "/api/mail/scheduled/" + first["id"] + "/cancel"
        self.assertEqual(self.client.post(url).json(), {"ok": True, "status": "canceled"})
        self.assertEqual(self.client.post(url).json(), {"ok": True, "status": "canceled"})
        for state in ["sending", "sent", "uncertain"]:
            with self.db() as db:
                db.get(ScheduledMail, first["id"]).status = state
                db.commit()
            response = self.client.post(url)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.current(first["id"]).json()["scheduled"][0]["status"], state)

    def test_failed_commit_rolls_back_creation(self):
        with self.db() as db:
            body = ScheduleBody(**self.body())
            with mock.patch.object(db, "commit", side_effect=RuntimeError("owned commit failure")):
                with self.assertRaises(RuntimeError):
                    schedule_send(self.aid, body, db)
            self.assertIsNone(db.get(ScheduledMail, body.request_id))

    def test_cancel_unconfirmed_request_prevents_late_create(self):
        scope = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"][0]
        for kind in ["schedule", "send-undoable"]:
            with self.subTest(kind=kind):
                body = self.body(recovery_scope=scope, delay=3600)
                url = "/api/mail/scheduled/" + body["request_id"] + "/cancel"
                params = {"recovery_scope": scope, "reserve_if_missing": True}
                self.assertEqual(self.client.post(url, params=params).status_code, 200)
                self.assertEqual(self.client.post(url, params=params).status_code, 200)
                self.assertEqual(self.queue(body, kind).status_code, 410)
                current = self.current(body["request_id"], recovery_scope=scope).json()["scheduled"]
                self.assertEqual(len(current), 1)
                self.assertEqual(current[0]["status"], "canceled")
                self.assertEqual(current[0]["request_kind"], "canceled-before-queue")
                for field in [
                    "account_id",
                    "to",
                    "cc",
                    "bcc",
                    "subject",
                    "body",
                    "html",
                    "in_reply_to",
                    "references",
                    "send_at",
                ]:
                    self.assertEqual(current[0][field], "")
        self.assertEqual(self.client.get("/api/mail/scheduled").json()["scheduled"], [])

    def test_cancel_reservation_requires_identity_and_scope_and_preserves_legacy_missing(self):
        scope = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"][0]
        url = "/api/mail/scheduled/" + str(uuid4()) + "/cancel"
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(
            self.client.post(url, params={"reserve_if_missing": True}).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                url, params={"reserve_if_missing": True, "recovery_scope": "f" * 64}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/mail/scheduled/invalid/cancel",
                params={"reserve_if_missing": True, "recovery_scope": scope},
            ).status_code,
            400,
        )
        with self.db() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 0)

    def test_failed_cancel_reservation_commit_does_not_block_a_later_create(self):
        scope = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"][0]
        body = self.body(recovery_scope=scope)
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("owned commit failure")):
                with self.assertRaises(RuntimeError):
                    cancel_scheduled(body["request_id"], db, scope, True)
            self.assertIsNone(db.get(ScheduledMail, body["request_id"]))
        self.assertEqual(self.queue(body).status_code, 200)

    def test_cancel_and_create_connections_keep_cancellation_after_reopen(self):
        scope = self.client.get("/api/mail/scheduled?context=true").json()["recovery_scopes"][0]
        with tempfile.TemporaryDirectory(prefix="alles-outbox-cancel-create-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'owned.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                with sessions() as db:
                    db.add(MailAccount(id=self.aid, email="owned@example.invalid"))
                    db.commit()
                for order in ["cancel-first", "create-first", "together"]:
                    body = self.body(recovery_scope=scope)
                    barrier = threading.Barrier(2) if order == "together" else None

                    def create():
                        with sessions() as db:
                            if barrier:
                                barrier.wait(timeout=10)
                            try:
                                return schedule_send(self.aid, ScheduleBody(**body), db)
                            except HTTPException as error:
                                return error.status_code

                    def cancel():
                        with sessions() as db:
                            if barrier:
                                barrier.wait(timeout=10)
                            return cancel_scheduled(body["request_id"], db, scope, True)

                    with self.subTest(order=order):
                        if barrier:
                            with ThreadPoolExecutor(max_workers=2) as pool:
                                a, b = pool.submit(create), pool.submit(cancel)
                                created, canceled = a.result(timeout=20), b.result(timeout=20)
                        elif order == "cancel-first":
                            canceled, created = cancel(), create()
                        else:
                            created, canceled = create(), cancel()
                        self.assertEqual(canceled, {"ok": True, "status": "canceled"})
                        if order == "cancel-first":
                            self.assertEqual(created, 410)
                        engine.dispose()
                        with sessions() as db:
                            self.assertEqual(
                                db.get(ScheduledMail, body["request_id"]).status, "canceled"
                            )
                            from services.mail_outbox import process_due

                            delivery = mock.Mock()
                            self.assertEqual(
                                process_due(db, now_iso="9999-12-31T00:00:00", send_fn=delivery), 0
                            )
                            delivery.assert_not_called()
            finally:
                engine.dispose()

    def test_concurrent_create_replay_and_conflicting_payload_are_serialized(self):
        with tempfile.TemporaryDirectory(prefix="alles-outbox-concurrency-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'owned.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            with sessions() as db:
                db.add(MailAccount(id=self.aid, email="owned@example.invalid"))
                db.commit()

            def race(requests):
                barrier = threading.Barrier(2)

                def write(body):
                    with sessions() as db:
                        barrier.wait(timeout=10)
                        try:
                            return schedule_send(self.aid, ScheduleBody(**body), db)
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    return [f.result(timeout=20) for f in [pool.submit(write, b) for b in requests]]

            try:
                body = self.body()
                result = race([body, body])
                self.assertEqual(result[0], result[1])
                with sessions() as db:
                    self.assertEqual(db.query(ScheduledMail).count(), 1)
                body = self.body()
                result = race([body, body | {"subject": "other intent"}])
                self.assertIn(409, result)
                self.assertEqual(sum(isinstance(x, dict) for x in result), 1)
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(db.query(ScheduledMail).count(), 2)
            finally:
                engine.dispose()

    def test_retries_and_cancel_rejections_release_reservations(self):
        with tempfile.TemporaryDirectory(prefix="alles-outbox-reservation-") as root:
            engine = create_engine(
                f"sqlite:///{Path(root) / 'owned.db'}", connect_args={"timeout": 0.1}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                with sessions() as db:
                    db.add(MailAccount(id=self.aid, email="owned@example.invalid"))
                    db.commit()
                with sessions() as db:
                    body = UndoableBody(**self.body(delay=3600))
                    row = send_undoable(self.aid, body, db)
                    self.assertEqual(send_undoable(self.aid, body, db), row)
                    with sessions() as other:
                        item = other.get(ScheduledMail, row["id"])
                        item.status = "sending"
                        other.commit()
                    with self.assertRaises(HTTPException):
                        cancel_scheduled(row["id"], db)
                    with sessions() as other:
                        item = other.get(ScheduledMail, row["id"])
                        item.status = "sent"
                        other.commit()
                    self.assertEqual(send_undoable(self.aid, body, db)["status"], "sent")
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_preserves_legacy_content(self):
        from core.migrations.m0058_mail_outbox_recovery import up

        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE mail_scheduled (id VARCHAR PRIMARY KEY, body TEXT, send_at VARCHAR, status VARCHAR)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO mail_scheduled VALUES ('owned','exact body','2099-01-01T09:00','uncertain')"
                    )
                )
                up(conn)
                up(conn)
                self.assertEqual(
                    conn.execute(text("SELECT * FROM mail_scheduled")).one(),
                    ("owned", "exact body", "2099-01-01T09:00", "uncertain", "", None),
                )
        finally:
            engine.dispose()

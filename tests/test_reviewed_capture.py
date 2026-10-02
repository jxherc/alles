"""Reviewed Inbox commitments use existing Plan records and preserve their origin."""

import json
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.database import (
    Base,
    Calendar,
    CalendarEvent,
    CommitmentCreateReceipt,
    MailAccount,
    ModelEndpoint,
    Task,
)
from tests._client import ApiTest


class ReviewedCaptureTests(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            account = MailAccount(name="capture fixture", email="me@example.invalid")
            db.add(account)
            db.add(
                ModelEndpoint(
                    name="capture fixture",
                    base_url="http://127.0.0.1:1/v1",
                    cached_models='["capture-fixture"]',
                    enabled=True,
                )
            )
            db.commit()
            self.account_id = account.id
        self.mail = {
            "uid": "701",
            "message_id": "<planning@fixture.invalid>",
            "from": "Teammate <teammate@example.invalid>",
            "to": "me@example.invalid",
            "subject": "planning from mail",
            "date": "2032-06-20",
            "text": "Meet June 20 at 11. Bring the plan.\nKeep this exact source.",
            "html": "",
        }
        self.origin = {
            "account_id": self.account_id,
            "folder": "INBOX",
            **self.mail,
        }

    def preview_task(self):
        response = self.client.post(
            "/api/mail/make-task",
            json={"title": self.mail["subject"], "preview": True, "source": self.origin},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def accept_task(self):
        preview = self.preview_task()
        body = {
            **preview["candidate"],
            "source": preview["source"],
            "request_id": str(uuid.uuid4()),
        }
        response = self.client.post("/api/tasks", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return body, response.json()

    def test_task_preview_creates_no_commitment_and_retains_source_identity(self):
        preview = self.preview_task()
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        self.assertTrue(preview["preview"])
        self.assertEqual(preview["kind"], "task")
        self.assertEqual(preview["candidate"]["title"], self.mail["subject"])
        self.assertEqual(preview["source"]["kind"], "mail")
        self.assertEqual(preview["source"]["account_id"], self.account_id)
        self.assertEqual(preview["source"]["uid"], "701")
        self.assertEqual(preview["source"]["message_id"], self.mail["message_id"])
        self.assertRegex(preview["source"]["fingerprint"], r"^[0-9a-f]{64}$")

    def test_event_extraction_preview_does_not_create_an_event(self):
        extracted = {
            "found": True,
            "title": "planning call",
            "start": "2032-06-20T11:00",
            "end": None,
            "location": "office",
            "all_day": False,
        }
        with (
            mock.patch(
                "services.llm.simple_complete",
                new=mock.AsyncMock(return_value=json.dumps(extracted)),
            ),
            mock.patch("services.calendar_events.default_duration", return_value=45),
        ):
            response = self.client.post(
                "/api/mail/extract-event",
                json={
                    "subject": self.mail["subject"],
                    "body": self.mail["text"],
                    "date": self.mail["date"],
                    "source": self.origin,
                    "preview": True,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        with self.db() as db:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        result = response.json()
        self.assertTrue(result["preview"])
        self.assertTrue(result["found"])
        self.assertEqual(result["kind"], "event")
        self.assertEqual(result["candidate"]["start_dt"], "2032-06-20T11:00")
        self.assertEqual(result["candidate"]["end_dt"], "2032-06-20T11:45:00")
        self.assertEqual(result["candidate"]["location"], "office")
        self.assertEqual(result["source"]["uid"], "701")

    def test_html_only_source_keeps_readable_excerpt_after_source_disappears(self):
        origin = self.origin | {
            "text": "",
            "html": "<head><style>private-style</style></head><p>Meet <b>June 20</b> at 11 &amp; bring the plan.</p><script>private-script</script>",
        }
        preview = self.client.post(
            "/api/mail/make-task",
            json={"title": "planning", "preview": True, "source": origin},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        source = preview.json()["source"]
        self.assertIn("Meet June 20 at 11 & bring the plan.", source["excerpt"])
        self.assertNotIn("private-", source["excerpt"])
        saved = self.client.post(
            "/api/tasks",
            json={"title": "planning", "source": source, "request_id": str(uuid.uuid4())},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        with mock.patch("services.mail.fetch_message", return_value={"error": "message not found"}):
            missing = self.client.get("/api/mail/source/task/" + saved.json()["id"])
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["detail"]["source"]["excerpt"], source["excerpt"])

    def test_html_only_preview_extraction_receives_the_readable_body(self):
        origin = self.origin | {"text": "", "html": "<p>Meet June 20 at 11.</p>"}
        with mock.patch(
            "services.llm.simple_complete",
            new=mock.AsyncMock(return_value='{"found": false}'),
        ) as complete:
            response = self.client.post(
                "/api/mail/extract-event",
                json={"subject": "planning", "preview": True, "source": origin},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Meet June 20 at 11.", complete.call_args.args[0][1]["content"])
        with self.db() as db:
            self.assertEqual(db.query(CalendarEvent).count(), 0)

    def test_excerpt_prefers_original_plain_text_and_bounds_html_fallback(self):
        for origin, expected in [
            (self.origin | {"text": "  exact\ntext  ", "html": "<p>other</p>"}, "  exact\ntext  "),
            (self.origin | {"text": "  ", "html": "<p>" + "a" * 7000 + "</p>"}, "a" * 6000),
        ]:
            with self.subTest(expected_length=len(expected)):
                response = self.client.post(
                    "/api/mail/make-task",
                    json={"title": "planning", "preview": True, "source": origin},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["source"]["excerpt"], expected)

    def test_omitted_head_end_keeps_visible_capture_and_extraction_text(self):
        for html in [
            "<head><meta charset=utf-8><body><p>Meet June 20 at 11.</p>",
            "<html><head><title>private-title</title><p>Meet June 20 at 11.</p>",
            "<head><style>private-style</style><script>private-script</script><body>Meet June 20 at 11.",
            "<head><template><template>private-inner</template>private-outer</template><body>Meet June 20 at 11.",
        ]:
            with self.subTest(html=html):
                origin = self.origin | {"text": "", "html": html}
                preview = self.client.post(
                    "/api/mail/make-task",
                    json={"title": "planning", "preview": True, "source": origin},
                )
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertEqual(preview.json()["source"]["excerpt"], "Meet June 20 at 11.")
                with mock.patch(
                    "services.llm.simple_complete",
                    new=mock.AsyncMock(return_value='{"found": false}'),
                ) as complete:
                    response = self.client.post(
                        "/api/mail/extract-event",
                        json={"subject": "planning", "preview": True, "source": origin},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                prompt = complete.call_args.args[0][1]["content"]
                self.assertIn("Meet June 20 at 11.", prompt)
                self.assertNotIn("private-", prompt)

    def test_acceptance_retry_returns_current_task_or_event_without_duplication(self):
        for endpoint, payload in [
            ("/api/tasks", {"title": "review the plan"}),
            (
                "/api/calendar",
                {"title": "planning call", "start_dt": "2032-06-20T11:00"},
            ),
        ]:
            with self.subTest(endpoint=endpoint):
                body = payload | {"request_id": str(uuid.uuid4())}
                first = self.client.post(endpoint, json=body)
                self.assertEqual(first.status_code, 200, first.text)
                rid = first.json()["id"]
                edited = self.client.patch(endpoint + "/" + rid, json={"title": "edited later"})
                self.assertEqual(edited.status_code, 200, edited.text)
                retry = self.client.post(endpoint, json=body)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(retry.json()["id"], rid)
                self.assertEqual(retry.json()["title"], "edited later")
                self.assertEqual(len(self.client.get(endpoint).json()), 1)

    def test_changed_acceptance_conflicts_and_deleted_target_is_not_recreated(self):
        for endpoint, payload in [
            ("/api/tasks", {"title": "review the plan"}),
            (
                "/api/calendar",
                {"title": "planning call", "start_dt": "2032-06-20T11:00"},
            ),
        ]:
            with self.subTest(endpoint=endpoint):
                body = payload | {"request_id": str(uuid.uuid4())}
                first = self.client.post(endpoint, json=body)
                self.assertEqual(first.status_code, 200, first.text)
                rid = first.json()["id"]
                changed = self.client.post(endpoint, json=body | {"title": "another intent"})
                self.assertEqual(changed.status_code, 409, changed.text)
                self.assertEqual(self.client.delete(endpoint + "/" + rid).status_code, 200)
                retry = self.client.post(endpoint, json=body)
                self.assertEqual(retry.status_code, 410, retry.text)
                self.assertEqual(self.client.get(endpoint).json(), [])

    def test_source_survives_task_edit_completion_and_reload(self):
        body, saved = self.accept_task()
        rid = saved["id"]
        changed = self.client.patch(
            "/api/tasks/" + rid,
            json={"title": "accepted edited title", "notes": "my own notes", "done": True},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        reloaded = self.client.get("/api/tasks/done")
        self.assertEqual(reloaded.status_code, 200, reloaded.text)
        current = next(row for row in reloaded.json() if row["id"] == rid)
        self.assertTrue(current["done"])
        self.assertEqual(current["source"], saved["source"])
        with mock.patch("services.mail.fetch_message", return_value=self.mail) as fetch:
            source = self.client.get("/api/mail/source/task/" + rid)
        self.assertEqual(source.status_code, 200, source.text)
        self.assertEqual(source.json()["message"]["text"], self.mail["text"])
        self.assertEqual(fetch.call_args.args[1:], ("701", "INBOX"))
        retry = self.client.post("/api/tasks", json=body)
        self.assertEqual(retry.json()["id"], rid)
        self.assertTrue(retry.json()["done"])

    def test_source_lookup_rejects_reused_uid_or_changed_content(self):
        _, saved = self.accept_task()
        endpoint = "/api/mail/source/task/" + saved["id"]
        for replacement in [
            self.mail | {"message_id": "<another@fixture.invalid>"},
            self.mail | {"text": "the source changed"},
        ]:
            with self.subTest(replacement=replacement):
                with mock.patch("services.mail.fetch_message", return_value=replacement):
                    response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertNotIn("message", response.json())
        with mock.patch("services.mail.fetch_message", return_value={"error": "message not found"}):
            response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 404, response.text)

    def test_origin_control_characters_are_rejected_before_preview(self):
        for field in ("folder", "account_id"):
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/mail/make-task",
                    json={
                        "title": "review",
                        "preview": True,
                        "source": self.origin | {field: "invalid\r\nreference"},
                    },
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_source_read_bypasses_stale_mail_cache(self):
        _, saved = self.accept_task()
        from services import mail

        with (
            mock.patch.object(mail, "_cached", return_value=self.mail),
            mock.patch.object(mail, "_imap", return_value=mock.Mock()),
            mock.patch.object(
                mail, "_fetch_message_parts", return_value=self.mail | {"text": "reused uid"}
            ) as live,
            mock.patch.object(mail, "_release_imap"),
            mock.patch.object(mail, "_put_cache"),
        ):
            response = self.client.get("/api/mail/source/task/" + saved["id"])
        self.assertEqual(response.status_code, 409, response.text)
        live.assert_called_once()

    def test_task_recurrence_and_calendar_split_preserve_source(self):
        source = self.preview_task()["source"]
        task = self.client.post(
            "/api/tasks",
            json={
                "title": "daily review",
                "source": source,
                "due_date": "2032-06-20",
                "repeat": "daily",
            },
        ).json()
        completed = self.client.patch("/api/tasks/" + task["id"], json={"done": True})
        self.assertEqual(completed.status_code, 200, completed.text)
        spawned = self.client.get("/api/tasks").json()
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0]["source"], source)
        self.assertEqual(spawned[0]["due_date"], "2032-06-21")
        for scope in ("this", "following"):
            with self.subTest(scope=scope):
                saved = self.client.post(
                    "/api/calendar",
                    json={
                        "title": "daily planning",
                        "source": source,
                        "start_dt": "2032-06-20T11:00",
                        "recurrence": "daily",
                        "recur_count": 5,
                    },
                ).json()
                split = self.client.patch(
                    "/api/calendar/" + saved["id"] + "?scope=" + scope + "&occ=2032-06-22",
                    json={"title": "changed"},
                )
                self.assertEqual(split.status_code, 200, split.text)
                self.assertEqual(split.json()["source"], source)

    def test_failed_event_create_rolls_back_receipt_default_calendar_and_adoption(self):
        with self.db() as db:
            db.query(Calendar).delete()
            orphan = CalendarEvent(title="legacy event", start_dt="2032-06-20", calendar_id="")
            db.add(orphan)
            db.commit()
            orphan_id = orphan.id

        def fail_insert(*_args):
            raise RuntimeError("synthetic insert failure")

        event.listen(CalendarEvent, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic insert failure"):
                self.client.post(
                    "/api/calendar",
                    json={
                        "title": "reviewed",
                        "start_dt": "2032-06-21T11:00",
                        "request_id": str(uuid.uuid4()),
                    },
                )
        finally:
            event.remove(CalendarEvent, "before_insert", fail_insert)
        with self.db() as db:
            self.assertEqual(db.query(Calendar).count(), 0)
            self.assertEqual(db.query(CommitmentCreateReceipt).count(), 0)
            self.assertEqual(db.get(CalendarEvent, orphan_id).calendar_id, "")


class ReviewedCaptureConcurrencyTests(ApiTest):
    def test_simultaneous_acceptances_share_one_target_and_release_reservations(self):
        from routes.tasks import TaskBody, create_task
        from services.calendar_events import create_event, event_dict

        for kind in ("task", "event"):
            with (
                self.subTest(kind=kind),
                tempfile.TemporaryDirectory(prefix="alles-capture-race-") as root,
            ):
                engine = create_engine(
                    "sqlite:///" + str(Path(root) / "race.sqlite"),
                    connect_args={"check_same_thread": False, "timeout": 0.5},
                )
                try:
                    Base.metadata.create_all(engine)
                    sessions = sessionmaker(bind=engine, autoflush=False)
                    barrier = threading.Barrier(2)
                    body = {"request_id": str(uuid.uuid4()), "title": "reviewed"}
                    if kind == "event":
                        body["start_dt"] = "2032-06-20T11:00"

                    def create(db, payload):
                        return (
                            create_task(TaskBody(**payload), db)
                            if kind == "task"
                            else event_dict(create_event(db, payload))
                        )

                    def contender(_index):
                        with sessions() as db:
                            barrier.wait(timeout=5)
                            return create(db, body)

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(contender, range(2)))
                    self.assertEqual(results[0]["id"], results[1]["id"])
                    model = Task if kind == "task" else CalendarEvent
                    with sessions() as db:
                        self.assertEqual(db.query(model).count(), 1)
                        self.assertEqual(db.query(CommitmentCreateReceipt).count(), 1)
                        if kind == "event":
                            self.assertEqual(db.query(Calendar).count(), 1)
                    for state in ("replay", "conflict", "deleted"):
                        with self.subTest(state=state), sessions() as held:
                            if state == "deleted":
                                with sessions() as db:
                                    db.query(model).delete()
                                    db.commit()
                            if state == "replay":
                                create(held, body)
                            else:
                                with self.assertRaises(HTTPException) as error:
                                    create(
                                        held,
                                        body
                                        | ({"title": "different"} if state == "conflict" else {}),
                                    )
                                self.assertEqual(
                                    error.exception.status_code, 409 if state == "conflict" else 410
                                )
                            # The first session intentionally stays open during this independent write.
                            with sessions() as db:
                                create(
                                    db,
                                    body
                                    | {
                                        "request_id": str(uuid.uuid4()),
                                        "title": "another " + state,
                                    },
                                )
                finally:
                    engine.dispose()

    def test_migration_preserves_legacy_records_and_can_run_twice(self):
        from core.migrations.m0055_commitment_sources import up

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                for table in ("tasks", "calendar_events"):
                    conn.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, title TEXT)"))
                    conn.execute(text(f"INSERT INTO {table} VALUES ('legacy', 'keep exact')"))
                up(conn)
                up(conn)
                for table in ("tasks", "calendar_events"):
                    self.assertEqual(
                        tuple(conn.execute(text(f"SELECT * FROM {table}")).one()),
                        ("legacy", "keep exact", "{}"),
                    )
                self.assertEqual(
                    conn.execute(text("SELECT COUNT(*) FROM commitment_create_receipts")).scalar(),
                    0,
                )
        finally:
            engine.dispose()

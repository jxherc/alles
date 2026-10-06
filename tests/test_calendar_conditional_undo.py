import json
import os
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from services import calendar_events, events
from tests._client import ApiTest, db

CalendarEvent = db.CalendarEvent
EventAttendee = db.EventAttendee


class CalendarConditionalUndoTest(ApiTest):
    def mutations(self, eid):
        with self.db() as session:
            return [
                {
                    "id": row.id,
                    "entity_kind": row.entity_kind,
                    "entity_id": row.entity_id,
                    "op": row.op,
                    "fields": json.loads(row.fields),
                    "actor": row.actor,
                    "ts": row.ts.isoformat(),
                }
                for row in events.history(session, "calendar_events", eid)
            ]

    @contextmanager
    def notifications(self):
        batches = []
        with mock.patch.object(
            events, "_subscribers", [lambda batch: batches.append(deepcopy(batch))]
        ):
            yield batches

    def create(self, **values):
        response = self.client.post(
            "/api/calendar",
            json={"title": "owned event", "start_dt": "2026-10-07T13:00", **values},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def invite(self, eid):
        # Seed local tokens directly; this regression never invokes email delivery.
        with self.db() as session:
            attendee = EventAttendee(
                event_id=eid, name="owned attendee", email="fixture@example.test"
            )
            session.add(attendee)
            session.commit()
            return attendee.id, attendee.token

    def undo(self, saved, suffix="", body=None):
        return self.client.request(
            "DELETE", f"/api/calendar/{saved['id']}{suffix}", json=saved if body is None else body
        )

    def saved(self, eid):
        with self.db() as session:
            row = session.get(CalendarEvent, eid)
            return calendar_events.event_dict(row) if row is not None else None

    def assert_attendee(self, aid, present):
        with self.db() as session:
            self.assertEqual(session.get(EventAttendee, aid) is not None, present)

    def test_unchanged_quick_receipt_deletes_only_its_event_and_tokens(self):
        response = self.client.post(
            "/api/calendar/quick", json={"text": "owned lunch tomorrow 1pm"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()
        aid, token = self.invite(original["id"])
        other = self.create(title="unrelated event")
        other_aid, _ = self.invite(other["id"])
        deleted = self.undo(original)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json(), {"ok": True})
        self.assertIsNone(self.saved(original["id"]))
        self.assert_attendee(aid, False)
        self.assertEqual(self.saved(other["id"]), other)
        self.assert_attendee(other_aid, True)
        self.assertEqual(
            self.client.post(f"/rsvp/{token}", json={"status": "accepted"}).status_code, 404
        )
        # Replaying the same receipt after a lost acknowledgment retains the existing 404 contract.
        self.assertEqual(self.undo(original).status_code, 404)
        self.assert_attendee(other_aid, True)

    def test_newer_saved_values_refuse_undo_and_keep_attendee_tokens(self):
        original = self.create()
        aid, _ = self.invite(original["id"])
        changed = self.client.patch(
            f"/api/calendar/{original['id']}",
            json={
                "title": "newer title",
                "description": "newer notes",
                "start_dt": "2026-10-07T12:00",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        history = self.mutations(original["id"])
        with self.notifications() as notifications:
            refused = self.undo(original)
        self.assertEqual(notifications, [])
        self.assertEqual(self.mutations(original["id"]), history)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(self.saved(original["id"]), changed.json())
        self.assert_attendee(aid, True)

    def test_expected_is_the_entire_exact_event_dictionary(self):
        original = self.create()
        aid, _ = self.invite(original["id"])
        variants = [
            {"id": original["id"]},
            {**original, "extra": "not in the receipt"},
            {**original, "id": "another-event"},
            {**original, "description": "different"},
            {**original, "all_day": 0},
            {**original, "recur_interval": 1.0},
        ]
        missing = deepcopy(original)
        missing.pop("created_at")
        variants.append(missing)
        for expected in variants:
            with self.subTest(expected=expected):
                result = self.undo(original, body=expected)
                self.assertEqual(result.status_code, 409, result.text)
                self.assertEqual(self.saved(original["id"]), original)
                self.assert_attendee(aid, True)

    def test_expected_rejects_partial_scopes_occurrences_and_non_objects(self):
        original = self.create(recurrence="daily")
        aid, _ = self.invite(original["id"])
        for suffix in [
            "?scope=this",
            "?scope=following",
            "?scope=unknown",
            "?scope=all&occ=2026-10-07",
        ]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.undo(original, suffix).status_code, 422)
        for body in [[], "invalid", 7, True]:
            with self.subTest(body=body):
                self.assertEqual(self.undo(original, body=body).status_code, 422)
        self.assertEqual(self.saved(original["id"]), original)
        self.assert_attendee(aid, True)
        mismatch = self.client.request("DELETE", "/api/calendar/missing", json=original)
        self.assertEqual(mismatch.status_code, 409)
        matching_missing = self.client.request(
            "DELETE", "/api/calendar/missing", json={**original, "id": "missing"}
        )
        self.assertEqual(matching_missing.status_code, 404)

    def test_no_body_clients_keep_explicit_all_and_recurrence_deletion(self):
        original = self.create()
        aid, _ = self.invite(original["id"])
        self.assertEqual(self.client.delete(f"/api/calendar/{original['id']}").status_code, 200)
        self.assertIsNone(self.saved(original["id"]))
        self.assert_attendee(aid, False)
        for scope in ["this", "following"]:
            with self.subTest(scope=scope):
                series = self.create(recurrence="daily", recur_count=5)
                series_aid, _ = self.invite(series["id"])
                response = self.client.delete(
                    f"/api/calendar/{series['id']}?scope={scope}&occ=2026-10-09"
                )
                self.assertEqual(response.status_code, 200, response.text)
                saved = self.saved(series["id"])
                if scope == "this":
                    self.assertEqual(saved["recur_except"], ["2026-10-09"])
                else:
                    self.assertEqual(saved["recur_until"], "2026-10-08")
                    self.assertIsNone(saved["recur_count"])
                self.assert_attendee(series_aid, True)

    def test_event_and_tokens_roll_back_together_on_cleanup_or_commit_failure(self):
        for failure in ["attendee", "commit"]:
            with self.subTest(failure=failure):
                original = self.create()
                aid, _ = self.invite(original["id"])
                statements = []

                def interrupt(_connection, _cursor, statement, _parameters, _context, _many):
                    if statement.startswith(
                        ("DELETE FROM calendar_events", "DELETE FROM event_attendees")
                    ):
                        statements.append(statement.split(" WHERE")[0])
                        if failure == "attendee" and statement.startswith(
                            "DELETE FROM event_attendees"
                        ):
                            raise RuntimeError("owned attendee interruption")

                history = self.mutations(original["id"])
                rolled_back = []

                def after_rollback(session):
                    rolled_back.append(deepcopy(session.info.get("_mutations", [])))

                event.listen(self.eng, "before_cursor_execute", interrupt)
                event.listen(db.SessionLocal, "after_rollback", after_rollback)
                try:
                    with (
                        self.notifications() as notifications,
                        mock.patch.object(
                            events, "record_mutation", wraps=events.record_mutation
                        ) as record,
                    ):
                        if failure == "commit":
                            original_commit = Session.commit

                            def interrupt_delete_commit(session):
                                if any(
                                    mutation.get("entity_kind") == "calendar_events"
                                    and mutation.get("entity_id") == original["id"]
                                    and mutation.get("op") == "delete"
                                    for mutation in session.info.get("_mutations", [])
                                ):
                                    raise RuntimeError("owned commit interruption")
                                return original_commit(session)

                            with mock.patch.object(Session, "commit", interrupt_delete_commit):
                                with self.assertRaisesRegex(
                                    RuntimeError, "owned commit interruption"
                                ):
                                    self.undo(original)
                        else:
                            with self.assertRaisesRegex(
                                RuntimeError, "owned attendee interruption"
                            ):
                                self.undo(original)
                        self.assertEqual(record.call_count, 1 if failure == "commit" else 0)
                finally:
                    event.remove(self.eng, "before_cursor_execute", interrupt)
                    event.remove(db.SessionLocal, "after_rollback", after_rollback)
                self.assertEqual(
                    rolled_back, [[]], "rollback must discard queued subscriber payloads"
                )
                self.assertEqual(notifications, [])
                self.assertEqual(self.mutations(original["id"]), history)
                self.assertEqual(
                    statements, ["DELETE FROM calendar_events", "DELETE FROM event_attendees"]
                )
                self.assertEqual(self.saved(original["id"]), original)
                self.assert_attendee(aid, True)
                self.assertEqual(self.undo(original).status_code, 200)

    def test_committed_edit_between_comparison_and_delete_cannot_be_removed(self):
        for field, value in [
            ("title", "concurrent newer title"),
            ("caldav_uid", "new-local-sync-identity"),
            ("source_json", " { } "),
            ("end_dt", "2026-10-07T14:00"),
        ]:
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory(
                    prefix="calendar-undo-race-", dir=os.environ["ALLES_DATA"]
                ) as directory,
            ):
                engine = create_engine(
                    f"sqlite:///{directory}/calendar.db", connect_args={"timeout": 5}
                )
                factory = sessionmaker(bind=engine, autoflush=False)
                try:
                    with engine.connect() as connection:
                        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                    db.Base.metadata.create_all(
                        engine,
                        tables=[
                            CalendarEvent.__table__,
                            EventAttendee.__table__,
                            db.MutationEvent.__table__,
                        ],
                    )
                    with factory() as session:
                        row = CalendarEvent(title="original", start_dt="2026-10-07T13:00")
                        session.add(row)
                        session.flush()
                        attendee = EventAttendee(event_id=row.id, name="owned race attendee")
                        session.add(attendee)
                        session.commit()
                        eid, aid = row.id, attendee.id
                    injected, token_deletes = [], []

                    def newer_edit(connection, _cursor, statement, _parameters, _context, _many):
                        if statement.startswith("DELETE FROM event_attendees"):
                            token_deletes.append(statement)
                        if not injected and statement.startswith("DELETE FROM calendar_events"):
                            injected.append(field)
                            with engine.begin() as writer:
                                self.assertIsNot(
                                    writer.connection.driver_connection,
                                    connection.connection.driver_connection,
                                )
                                writer.execute(
                                    CalendarEvent.__table__.update()
                                    .where(CalendarEvent.id == eid)
                                    .values(**{field: value})
                                )

                    with factory() as session:
                        row = session.get(CalendarEvent, eid)
                        expected = calendar_events.event_dict(row)
                        history = list(
                            session.execute(select(db.MutationEvent.__table__)).mappings()
                        )
                        event.listen(engine, "before_cursor_execute", newer_edit)
                        try:
                            with self.assertRaises(HTTPException) as refused:
                                calendar_events.delete_event(session, row, expected=expected)
                        finally:
                            event.remove(engine, "before_cursor_execute", newer_edit)
                        self.assertEqual(refused.exception.status_code, 409)
                        self.assertFalse(
                            session.in_transaction(), "the failed delete must roll back"
                        )
                        self.assertNotIn("_mutations", session.info)
                    self.assertEqual(injected, [field])
                    self.assertEqual(
                        token_deletes, [], "tokens must not retire before a matched delete"
                    )
                    with factory() as session:
                        self.assertEqual(getattr(session.get(CalendarEvent, eid), field), value)
                        self.assertIsNotNone(session.get(EventAttendee, aid))
                        self.assertEqual(
                            list(session.execute(select(db.MutationEvent.__table__)).mappings()),
                            history,
                        )
                finally:
                    engine.dispose()

    def test_ordinary_and_conditional_delete_record_once_before_subscribing_after_commit(self):
        for conditional in [False, True]:
            with self.subTest(conditional=conditional):
                original = self.create()
                aid, _ = self.invite(original["id"])
                stages, committed, notified = [], [], []

                def at_commit(connection):
                    if committed:
                        return
                    stages.append("database commit")
                    committed.append(
                        {
                            "events": list(
                                connection.execute(
                                    select(db.MutationEvent.id).where(
                                        db.MutationEvent.entity_id == original["id"],
                                        db.MutationEvent.op == "delete",
                                    )
                                ).scalars()
                            ),
                            "event": connection.execute(
                                select(CalendarEvent.id).where(CalendarEvent.id == original["id"])
                            ).first(),
                            "attendee": connection.execute(
                                select(EventAttendee.id).where(EventAttendee.id == aid)
                            ).first(),
                            "already_notified": deepcopy(notified),
                        }
                    )

                def subscriber(batch):
                    stages.append("subscriber")
                    notified.append(deepcopy(batch))

                event.listen(self.eng, "commit", at_commit)
                try:
                    with mock.patch.object(events, "_subscribers", [subscriber]):
                        response = (
                            self.undo(original)
                            if conditional
                            else self.client.delete(f"/api/calendar/{original['id']}")
                        )
                finally:
                    event.remove(self.eng, "commit", at_commit)
                self.assertEqual(response.status_code, 200, response.text)
                history = [row for row in self.mutations(original["id"]) if row["op"] == "delete"]
                self.assertEqual(len(history), 1)
                deleted = history[0]
                self.assertEqual(deleted["fields"], {})
                self.assertEqual(deleted["actor"], "")
                self.assertTrue(deleted["ts"])
                self.assertEqual(
                    committed,
                    [
                        {
                            "events": [deleted["id"]],
                            "event": None,
                            "attendee": None,
                            "already_notified": [],
                        }
                    ],
                )
                self.assertEqual(stages, ["database commit", "subscriber"])
                self.assertEqual(
                    notified,
                    [
                        [
                            {
                                "event_id": deleted["id"],
                                "entity_kind": "calendar_events",
                                "entity_id": original["id"],
                                "op": "delete",
                                "fields": {},
                            }
                        ]
                    ],
                )
                with self.notifications() as repeated:
                    response = self.undo(original)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(repeated, [])
                self.assertEqual(
                    [row for row in self.mutations(original["id"]) if row["op"] == "delete"],
                    history,
                )

    def test_mutation_writer_failure_keeps_existing_best_effort_delete_behavior(self):
        for conditional in [False, True]:
            with self.subTest(conditional=conditional):
                original = self.create()
                aid, _ = self.invite(original["id"])
                history = self.mutations(original["id"])
                with (
                    self.notifications() as notified,
                    mock.patch.object(
                        events,
                        "record_mutation",
                        side_effect=RuntimeError("owned mutation write failure"),
                    ) as record,
                    self.assertLogs("alles.events", level="WARNING") as warnings,
                ):
                    response = (
                        self.undo(original)
                        if conditional
                        else self.client.delete(f"/api/calendar/{original['id']}")
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(record.call_count, 1)
                self.assertIn("mutation-event listener failed", warnings.output[0])
                self.assertIsNone(self.saved(original["id"]))
                self.assert_attendee(aid, False)
                self.assertEqual(self.mutations(original["id"]), history)
                self.assertEqual(notified, [])

    def test_subscriber_failure_keeps_committed_event_and_later_subscribers(self):
        for conditional in [False, True]:
            with self.subTest(conditional=conditional):
                original = self.create()
                notified = []

                def broken_subscriber(_batch):
                    raise RuntimeError("owned subscriber failure")

                with (
                    mock.patch.object(
                        events,
                        "_subscribers",
                        [broken_subscriber, lambda batch: notified.append(deepcopy(batch))],
                    ),
                    self.assertLogs("alles.events", level="WARNING") as warnings,
                ):
                    response = (
                        self.undo(original)
                        if conditional
                        else self.client.delete(f"/api/calendar/{original['id']}")
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("mutation subscriber failed", warnings.output[0])
                self.assertIsNone(self.saved(original["id"]))
                history = [row for row in self.mutations(original["id"]) if row["op"] == "delete"]
                self.assertEqual(len(history), 1)
                self.assertEqual(len(notified), 1)
                self.assertEqual([item["event_id"] for item in notified[0]], [history[0]["id"]])

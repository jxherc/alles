"""delivery bookkeeping for the background reminder job."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest import mock

import app
from core.database import Message, ModelEndpoint, Reminder, Session
from tests._client import ApiTest


class FireDueReminderTests(ApiTest):
    def _due(self):
        d = self.db()
        r = Reminder(
            text="ping",
            trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            type="reminder",
        )
        d.add(r)
        d.commit()
        rid = r.id
        d.close()
        return rid

    def _run_job(self, delivered):
        async def fake_broadcast(payload):
            return {
                "sent": delivered,
                "failed": 0,
                "uncertain": 0,
                "pruned": 0,
                "total": delivered,
            }

        with mock.patch("services.push_delivery.broadcast_result", fake_broadcast):
            asyncio.run(app._fire_due_reminders())

    def test_push_delivered_marks_fired(self):
        rid = self._due()
        self._run_job(delivered=1)  # one browser got the push
        d = self.db()
        r = d.get(Reminder, rid)
        self.assertTrue(r.notified)
        self.assertTrue(r.fired)  # delivered -> done, won't linger or re-toast
        d.close()

    def test_no_subscribers_leaves_unfired(self):
        rid = self._due()
        self._run_job(delivered=0)  # no push subscriptions
        d = self.db()
        r = d.get(Reminder, rid)
        self.assertFalse(r.notified)
        self.assertFalse(r.fired)  # stays for the in-app toast path
        d.close()

    def test_uncertain_push_is_claimed_and_not_retried(self):
        rid = self._due()
        calls = []

        async def failed_broadcast(payload):
            calls.append(payload)
            raise RuntimeError("temporary push failure")

        with mock.patch("services.push_delivery.broadcast_result", failed_broadcast):
            asyncio.run(app._fire_due_reminders())
            asyncio.run(app._fire_due_reminders())

        d = self.db()
        r = d.get(Reminder, rid)
        self.assertTrue(r.notified)
        self.assertFalse(r.fired)
        self.assertEqual(len(calls), 1)
        d.close()

    def test_scheduled_message_without_session_stays_pending(self):
        d = self.db()
        r = Reminder(
            text="ping aide",
            trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            type="message",
            session_id="missing-session",
        )
        d.add(r)
        d.commit()
        rid = r.id
        d.close()

        self._run_job(delivered=0)

        d = self.db()
        self.assertFalse(d.get(Reminder, rid).fired)
        d.close()

    def test_scheduled_message_is_fired_with_session_messages(self):
        d = self.db()
        endpoint = ModelEndpoint(
            name="local", base_url="http://local.test", cached_models='["test-model"]'
        )
        d.add(endpoint)
        d.flush()
        session = Session(name="scheduled", model="test-model", endpoint_id=endpoint.id)
        d.add(session)
        d.flush()
        reminder = Reminder(
            text="give me an update",
            trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            type="message",
            session_id=session.id,
        )
        d.add(reminder)
        d.commit()
        rid = reminder.id
        session_id = session.id
        d.close()

        async def fake_stream(*args, **kwargs):
            yield {"delta": "all done"}

        with mock.patch("services.llm.stream_chat", fake_stream):
            self._run_job(delivered=0)

        d = self.db()
        self.assertTrue(d.get(Reminder, rid).fired)
        messages = d.query(Message).filter(Message.session_id == session_id).all()
        self.assertEqual(
            [(m.role, m.content) for m in messages],
            [
                ("user", "give me an update"),
                ("assistant", "all done"),
            ],
        )
        d.close()

    def test_inherited_model_delivers_once_and_preserves_automatic_selection(self):
        with self.db() as db:
            endpoint = ModelEndpoint(
                name="inherited",
                base_url="http://127.0.0.1:1/v1",
                cached_models='["inherited-fixture"]',
            )
            session = Session(name="scheduled inherited", model="")
            db.add_all([endpoint, session])
            db.flush()
            reminder = Reminder(
                text="inherited update",
                type="message",
                session_id=session.id,
                trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            )
            db.add(reminder)
            db.commit()
            sid, eid, rid = session.id, endpoint.id, reminder.id
        settings = {
            "model_roles": {"aide_chat": {"endpoint_id": eid, "model": "inherited-fixture"}}
        }
        calls = []

        async def stream(messages, base_url, api_key, model):
            calls.append(model)
            yield {"delta": "inherited response"}

        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch("services.model_resolver.load_settings", return_value=settings),
            mock.patch("services.llm.stream_chat", stream),
        ):
            self._run_job(delivered=0)
            self._run_job(delivered=0)
        self.assertEqual(calls, ["inherited-fixture"])
        with self.db() as db:
            self.assertTrue(db.get(Reminder, rid).fired)
            self.assertTrue(db.get(Reminder, rid).notified)
            self.assertEqual(db.query(Message).filter_by(session_id=sid).count(), 2)
            self.assertEqual(db.get(Session, sid).model, "")
            self.assertIsNone(db.get(Session, sid).endpoint_id)

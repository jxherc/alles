"""delivery bookkeeping for the background reminder job."""

import asyncio
from datetime import datetime, timedelta
from unittest import mock

import app
from core.database import Message, ModelEndpoint, Reminder, Session
from tests._client import ApiTest


class FireDueReminderTests(ApiTest):
    def _due(self):
        d = self.db()
        r = Reminder(
            text="ping", trigger_at=datetime.utcnow() - timedelta(minutes=1), type="reminder"
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

        with mock.patch("routes.push.broadcast_result", fake_broadcast):
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

        with mock.patch("routes.push.broadcast_result", failed_broadcast):
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
            trigger_at=datetime.utcnow() - timedelta(minutes=1),
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
        endpoint = ModelEndpoint(name="local", base_url="http://local.test")
        d.add(endpoint)
        d.flush()
        session = Session(name="scheduled", model="test-model", endpoint_id=endpoint.id)
        d.add(session)
        d.flush()
        reminder = Reminder(
            text="give me an update",
            trigger_at=datetime.utcnow() - timedelta(minutes=1),
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

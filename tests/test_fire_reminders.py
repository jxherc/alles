"""the background reminder job: a plain reminder whose web push actually reaches a
subscriber should be marked fired (so it doesn't linger in the active list or re-toast
on next app open); one with no live subscribers stays unfired so an open tab can still
toast it via /api/reminders/due."""

import asyncio
from datetime import datetime, timedelta
from unittest import mock

import app
from core.database import Reminder
from tests._client import ApiTest


class FireDueReminderTests(ApiTest):
    def _due(self):
        d = self.db()
        r = Reminder(text="ping", trigger_at=datetime.utcnow() - timedelta(minutes=1), type="reminder")
        d.add(r)
        d.commit()
        rid = r.id
        d.close()
        return rid

    def _run_job(self, delivered):
        async def fake_broadcast(payload):
            return delivered

        with mock.patch("routes.push.broadcast", fake_broadcast):
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
        self.assertTrue(r.notified)
        self.assertFalse(r.fired)  # stays for the in-app toast path
        d.close()

from datetime import datetime, timedelta

from core.database import CachedMessage, MailAccount, ScheduledMail
from services import mail_cache, mail_outbox
from tests._client import ApiTest


def _iso(dt):
    return dt.isoformat()


class MailOutboxTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = MailAccount(
            name="Me",
            email="me@x.com",
            imap_host="imap.x.com",
            smtp_host="smtp.x.com",
            username="me@x.com",
            password="pw",
        )
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _schedule(self, send_at, to="bob@x.com", subject="hi", body="yo"):
        return self.client.post(
            f"/api/mail/schedule/{self.aid}",
            json={"to": to, "subject": subject, "body": body, "send_at": send_at},
        ).json()

    def _msg(self, uid, subject="m", snoozed_until=""):
        db = self.db()
        db.add(
            CachedMessage(
                account_id=self.aid,
                folder="INBOX",
                uid=str(uid),
                sender="a@x.com",
                subject=subject,
                date="2026-06-10",
                date_ts=1,
                seen=True,
                snoozed_until=snoozed_until,
            )
        )
        db.commit()
        db.close()

    # ---- schedule / cancel ----
    def test_schedule_creates(self):
        d = self._schedule("2026-12-01T09:00:00")
        self.assertTrue(d["id"])
        self.assertEqual(d["status"], "scheduled")

    def test_scheduled_list_pending(self):
        self._schedule("2026-12-01T09:00:00", subject="future")
        d = self.client.get("/api/mail/scheduled").json()
        self.assertTrue(any(s["subject"] == "future" for s in d["scheduled"]))

    def test_cancel_scheduled(self):
        s = self._schedule("2026-12-01T09:00:00")
        self.client.post(f"/api/mail/scheduled/{s['id']}/cancel")
        d = self.client.get("/api/mail/scheduled").json()
        self.assertFalse(any(x["id"] == s["id"] for x in d["scheduled"]))

    # ---- process_due (the job) ----
    def test_process_due_sends_past(self):
        s = self._schedule("2020-01-01T00:00:00")
        sent = mail_outbox.process_due(self.db(), send_fn=lambda a, m: None)
        self.assertEqual(sent, 1)
        db = self.db()
        self.assertEqual(db.get(ScheduledMail, s["id"]).status, "sent")
        db.close()

    def test_process_due_skips_future(self):
        self._schedule("2099-01-01T00:00:00")
        sent = mail_outbox.process_due(self.db(), send_fn=lambda a, m: None)
        self.assertEqual(sent, 0)

    def test_process_due_skips_canceled(self):
        s = self._schedule("2020-01-01T00:00:00")
        self.client.post(f"/api/mail/scheduled/{s['id']}/cancel")
        sent = mail_outbox.process_due(self.db(), send_fn=lambda a, m: None)
        self.assertEqual(sent, 0)

    def test_send_undoable_schedules_future(self):
        d = self.client.post(
            f"/api/mail/send-undoable/{self.aid}",
            json={"to": "bob@x.com", "subject": "oops", "body": "b", "delay": 30},
        ).json()
        self.assertTrue(d["id"])
        # send_at should be in the (near) future so the undo window is open
        self.assertGreater(d["send_at"], datetime.utcnow().isoformat())
        listed = self.client.get("/api/mail/scheduled").json()["scheduled"]
        self.assertTrue(any(x["id"] == d["id"] for x in listed))

    # ---- snooze ----
    def test_snooze_hides_until_future(self):
        self._msg(1)
        future = _iso(datetime.utcnow() + timedelta(days=1))
        self.client.post(f"/api/mail/snooze/{self.aid}", json={"uid": "1", "until": future})
        self.assertEqual(mail_cache.get(self.db(), self.aid), [])

    def test_snooze_past_visible(self):
        self._msg(1, snoozed_until=_iso(datetime.utcnow() - timedelta(days=1)))
        self.assertEqual(len(mail_cache.get(self.db(), self.aid)), 1)

    def test_snoozed_reappears_after_time(self):
        # snoozed to a time already in the past → back in the inbox
        past = _iso(datetime.utcnow() - timedelta(minutes=5))
        self._msg(1, snoozed_until=past)
        uids = [m["uid"] for m in mail_cache.get(self.db(), self.aid)]
        self.assertIn("1", uids)

    def test_snoozed_list(self):
        self._msg(1)
        future = _iso(datetime.utcnow() + timedelta(days=1))
        self.client.post(f"/api/mail/snooze/{self.aid}", json={"uid": "1", "until": future})
        d = self.client.get(f"/api/mail/snoozed/{self.aid}").json()
        self.assertTrue(any(m["uid"] == "1" for m in d["snoozed"]))

    def test_unified_excludes_snoozed(self):
        self._msg(1, subject="now")
        self._msg(2, subject="later", snoozed_until=_iso(datetime.utcnow() + timedelta(days=1)))
        subs = [m["subject"] for m in mail_cache.get_unified(self.db())]
        self.assertIn("now", subs)
        self.assertNotIn("later", subs)

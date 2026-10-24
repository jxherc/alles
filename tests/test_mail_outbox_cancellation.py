"""Owned API probes only: no lifespan jobs and synthetic delivery functions."""

import unittest

from core.database import MailAccount, ScheduledMail
from services import mail_outbox
from tests._client import ApiTest


class OutboxRecoveryProbe(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            account = MailAccount(
                name="Owned fixture",
                email="owned@example.invalid",
                imap_host="127.0.0.1",
                imap_port=9,
                smtp_host="127.0.0.1",
                smtp_port=9,
                username="owned@example.invalid",
                password="",
                use_ssl=False,
            )
            db.add(account)
            db.commit()
            self.aid = account.id

    def queue(self):
        response = self.client.post(
            "/api/mail/schedule/" + self.aid,
            json={
                "to": "recipient@example.invalid",
                "subject": "owned fixture",
                "body": "synthetic delivery only",
                "send_at": "2032-01-01T09:00:00",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def test_cancel_scheduled_still_works(self):
        identity = self.queue()
        response = self.client.post("/api/mail/scheduled/" + identity + "/cancel")
        self.assertEqual(response.status_code, 200)
        with self.db() as db:
            self.assertEqual(db.get(ScheduledMail, identity).status, "canceled")

    def test_cancel_claimed_send_cannot_report_success(self):
        identity = self.queue()
        observed = []

        def synthetic_send(account, message):
            with self.db() as db:
                self.assertEqual(db.get(ScheduledMail, identity).status, "sending")
            response = self.client.post("/api/mail/scheduled/" + identity + "/cancel")
            observed.append((response.status_code, response.json()))

        with self.db() as db:
            count = mail_outbox.process_due(
                db, now_iso="2033-01-01T00:00:00", send_fn=synthetic_send
            )
        with self.db() as db:
            final = db.get(ScheduledMail, identity).status
        print(
            "claimed send cancellation",
            observed,
            "final",
            final,
            "synthetic sends",
            count,
            flush=True,
        )
        self.assertEqual(observed[0][0], 409)
        self.assertEqual(final, "sent")

    def test_cancel_uncertain_keeps_uncertainty_visible(self):
        identity = self.queue()

        def synthetic_unknown(account, message):
            raise RuntimeError("owned unknown delivery outcome")

        with self.db() as db:
            self.assertEqual(
                mail_outbox.process_due(
                    db, now_iso="2033-01-01T00:00:00", send_fn=synthetic_unknown
                ),
                0,
            )
        response = self.client.post("/api/mail/scheduled/" + identity + "/cancel")
        listed = self.client.get("/api/mail/scheduled").json()["scheduled"]
        with self.db() as db:
            final = db.get(ScheduledMail, identity).status
        print(
            "uncertain cancellation",
            response.status_code,
            response.json(),
            "final",
            final,
            "visible",
            any(row["id"] == identity for row in listed),
            flush=True,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(final, "uncertain")
        self.assertTrue(any(row["id"] == identity for row in listed))

    def make_uncertain(self, identity):
        def synthetic_unknown(account, message):
            raise RuntimeError("owned unknown delivery outcome")

        with self.db() as db:
            mail_outbox.process_due(db, now_iso="2033-01-01T00:00:00", send_fn=synthetic_unknown)
            self.assertEqual(db.get(ScheduledMail, identity).status, "uncertain")

    def test_dismiss_takes_an_uncertain_delivery_off_the_list_and_keeps_the_record(self):
        identity = self.queue()
        self.make_uncertain(identity)
        response = self.client.post(
            f"/api/mail/scheduled/{identity}/cancel", params={"dismiss": True}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "dismissed")
        listed = self.client.get("/api/mail/scheduled").json()["scheduled"]
        self.assertFalse(any(row["id"] == identity for row in listed))
        # the record is still there for a recovery read, and a retry is harmless
        one = self.client.get("/api/mail/scheduled", params={"request_id": identity}).json()
        self.assertEqual([row["status"] for row in one["scheduled"]], ["dismissed"])
        again = self.client.post(f"/api/mail/scheduled/{identity}/cancel", params={"dismiss": True})
        self.assertEqual((again.status_code, again.json()["changed"]), (200, False))

    def test_dismiss_never_cancels_a_pending_or_sent_delivery(self):
        def dismiss(identity):
            return self.client.post(
                f"/api/mail/scheduled/{identity}/cancel", params={"dismiss": True}
            )

        sent = self.queue()
        with self.db() as db:
            mail_outbox.process_due(
                db, now_iso="2033-01-01T00:00:00", send_fn=lambda account, message: None
            )
        pending = self.queue()
        self.assertEqual(dismiss(pending).status_code, 409)
        self.assertEqual(dismiss(sent).status_code, 409)
        with self.db() as db:
            self.assertEqual(db.get(ScheduledMail, pending).status, "scheduled")
            self.assertEqual(db.get(ScheduledMail, sent).status, "sent")
        self.assertEqual(dismiss("00000000-0000-4000-8000-000000000000").status_code, 404)

    def test_cancel_sent_does_not_relabel_history(self):
        identity = self.queue()
        with self.db() as db:
            self.assertEqual(
                mail_outbox.process_due(
                    db, now_iso="2033-01-01T00:00:00", send_fn=lambda account, message: None
                ),
                1,
            )
        response = self.client.post("/api/mail/scheduled/" + identity + "/cancel")
        with self.db() as db:
            final = db.get(ScheduledMail, identity).status
        print(
            "sent cancellation", response.status_code, response.json(), "final", final, flush=True
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(final, "sent")


if __name__ == "__main__":
    unittest.main(verbosity=2)

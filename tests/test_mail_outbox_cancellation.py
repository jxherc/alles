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

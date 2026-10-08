"""Controlled provider success must retain the user's local triage result."""

import unittest
from unittest.mock import patch

from core.database import CachedMessage, MailAccount
from services import mail as mailsvc
from tests._client import ApiTest


class OnlineTriageTests(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            db.add(MailAccount(id="online", name="owned", email="me@example.invalid", imap_host=""))
            db.add(
                CachedMessage(
                    account_id="online",
                    folder="INBOX",
                    uid="1",
                    sender="sender@example.invalid",
                    subject="triaged mail",
                    seen=False,
                    labels="work",
                )
            )
            db.commit()
        self.remote = {
            "uid": "1",
            "from": "sender@example.invalid",
            "subject": "triaged mail",
            "date_ts": 100,
            "seen": False,
        }

    def refresh(self):
        with patch.object(mailsvc, "fetch_inbox", return_value=[self.remote]):
            r = self.client.get("/api/mail/inbox/online")
        self.assertEqual(r.status_code, 200)
        return r.json()["messages"]

    def test_muted_stays_hidden_after_successful_provider_refresh(self):
        self.assertEqual(
            self.client.post("/api/mail/mute/online", json={"subject": "triaged mail"}).json()[
                "muted"
            ],
            1,
        )
        self.assertEqual(self.refresh(), [])

    def test_snoozed_stays_hidden_after_successful_provider_refresh(self):
        self.assertEqual(
            self.client.post(
                "/api/mail/snooze/online", json={"uid": "1", "until": "2099-01-01T00:00:00Z"}
            ).json()["snoozed"],
            1,
        )
        self.assertEqual(self.refresh(), [])

    def test_labels_stay_visible_after_successful_provider_refresh(self):
        self.assertEqual(self.refresh()[0].get("labels"), ["work"])

    def test_stale_high_timestamp_rows_cannot_consume_refresh_limit(self):
        with self.db() as db:
            db.add(CachedMessage(account_id="online", folder="INBOX", uid="stale", date_ts=999))
            db.add(CachedMessage(account_id="online", folder="Work", uid="other", date_ts=999))
            db.commit()
        with patch.object(mailsvc, "fetch_inbox", return_value=[self.remote]):
            response = self.client.get("/api/mail/inbox/online", params={"limit": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["uid"] for m in response.json()["messages"]], ["1"])
        with self.db() as db:
            self.assertEqual(
                {(r.folder, r.uid) for r in db.query(CachedMessage).all()},
                {("INBOX", "1"), ("Work", "other")},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

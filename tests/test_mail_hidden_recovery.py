"""Find hidden mail and undo a local mute without affecting another account."""

import unittest

from core.database import CachedMessage, MailAccount
from tests._client import ApiTest


class HiddenMailTests(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            for aid in ["A", "B"]:
                db.add(MailAccount(id=aid, name=aid, email=aid + "@example.invalid", imap_host=""))
            for aid, folder, uid, subject, muted, until in [
                ("A", "INBOX", "1", "Re: project", True, ""),
                ("A", "Work", "1", "project", True, ""),
                ("A", "INBOX", "2", "visible", False, ""),
                ("A", "Work", "3", "later", False, "2099-01-01T00:00:00Z"),
                ("B", "INBOX", "1", "project", True, ""),
                ("B", "INBOX", "3", "later", False, "2099-01-01T00:00:00Z"),
            ]:
                db.add(
                    CachedMessage(
                        account_id=aid,
                        folder=folder,
                        uid=uid,
                        subject=subject,
                        muted=muted,
                        snoozed_until=until,
                        seen=False,
                    )
                )
            db.commit()

    def test_muted_view_preserves_folders_and_account(self):
        r = self.client.get("/api/mail/smart/A", params={"filter": "muted"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            {(m["folder"], m["uid"]) for m in r.json()["messages"]}, {("INBOX", "1"), ("Work", "1")}
        )
        self.assertTrue(all(m["muted"] for m in r.json()["messages"]))

    def test_snoozed_view_preserves_folders_and_account(self):
        r = self.client.get("/api/mail/smart/A", params={"filter": "snoozed"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(m["folder"], m["uid"]) for m in r.json()["messages"]], [("Work", "3")])

    def test_unmute_changes_only_matching_account_thread(self):
        r = self.client.post("/api/mail/mute/A", json={"subject": "FW: project", "muted": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["muted"], 2)
        with self.db() as db:
            for row in db.query(CachedMessage).filter_by(uid="1"):
                self.assertEqual(row.muted, row.account_id == "B")
        self.assertEqual(
            self.client.get("/api/mail/smart/A", params={"filter": "muted"}).json()["messages"], []
        )

    def test_default_mute_still_mutes_after_restoration(self):
        self.client.post("/api/mail/mute/A", json={"subject": "project", "muted": False})
        self.assertEqual(
            self.client.post("/api/mail/mute/A", json={"subject": "project"}).json()["muted"], 2
        )
        with self.db() as db:
            self.assertTrue(
                all(row.muted for row in db.query(CachedMessage).filter_by(account_id="A", uid="1"))
            )

    def test_hidden_views_respect_zero_and_one_limits(self):
        for kind in ["muted", "snoozed"]:
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.client.get(
                        "/api/mail/smart/A", params={"filter": kind, "limit": 0}
                    ).json()["messages"],
                    [],
                )
                self.assertEqual(
                    len(
                        self.client.get(
                            "/api/mail/smart/A", params={"filter": kind, "limit": 1}
                        ).json()["messages"]
                    ),
                    1,
                )

    def test_unsnooze_preserves_other_folder_and_account(self):
        with self.db() as db:
            db.add(
                CachedMessage(
                    account_id="A",
                    folder="INBOX",
                    uid="3",
                    subject="other later",
                    snoozed_until="2100-01-01T00:00:00Z",
                )
            )
            db.commit()
        response = self.client.post(
            "/api/mail/snooze/A", json={"folder": "Work", "uid": "3", "until": ""}
        )
        self.assertEqual(response.json()["snoozed"], 1)
        remaining = self.client.get("/api/mail/smart/A", params={"filter": "snoozed"}).json()[
            "messages"
        ]
        self.assertEqual([(row["folder"], row["uid"]) for row in remaining], [("INBOX", "3")])
        with self.db() as db:
            self.assertEqual(
                db.query(CachedMessage)
                .filter_by(account_id="A", folder="Work", uid="3")
                .one()
                .snoozed_until,
                "",
            )
            self.assertEqual(
                db.query(CachedMessage).filter_by(account_id="B", uid="3").one().snoozed_until,
                "2099-01-01T00:00:00Z",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

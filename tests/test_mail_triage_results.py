"""Checked server responses and exact local message identities for mail triage."""

import unittest
from unittest.mock import patch

from core.database import CachedMessage, MailAccount
from services import mail as mailsvc
from tests._client import ApiTest
from tests.test_mail_move import FakeIMAP


class MoveResponseTests(unittest.TestCase):
    def test_rejected_stage_stops_remaining_commands(self):
        for stage, move, uidplus in [
            ("select", True, False),
            ("move", True, False),
            ("copy", False, True),
            ("store", False, True),
            ("expunge", False, True),
            ("expunge", False, False),
        ]:
            with self.subTest(stage=stage, move=move, uidplus=uidplus):
                fake = FakeIMAP(has_move=move, has_uidplus=uidplus)
                for method in ["select", "uid", "expunge"]:
                    original = getattr(fake, method)

                    def call(*args, original=original, method=method, **kwargs):
                        result = original(*args, **kwargs)
                        command = str(args[0]).lower() if method == "uid" else method
                        return ("NO", [b"owned rejection"]) if command == stage else result

                    setattr(fake, method, call)
                with self.assertRaises(Exception):
                    mailsvc._do_move(fake, "42", "Archive", "Work")
                last = fake.calls[-1]
                self.assertEqual(last[1] if last[0] == "uid" else last[0], stage)


class TriageResultsTests(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            db.add(MailAccount(id="A", name="A", email="me@example.invalid", imap_host=""))
            db.add(
                CachedMessage(account_id="A", folder="Work", uid="1", subject="mail", seen=False)
            )
            db.add(
                CachedMessage(
                    account_id="A", folder="INBOX", uid="1", subject="different mail", seen=False
                )
            )
            db.commit()

    def test_strict_archive_keeps_local_message_when_server_fails(self):
        with patch.object(mailsvc, "move_message", side_effect=OSError("owned failure")):
            response = self.client.post(
                "/api/mail/archive/A", json={"uid": "1", "folder": "Work", "require_server": True}
            )
        self.assertEqual(response.status_code, 502)
        with self.db() as db:
            self.assertIsNotNone(
                db.query(CachedMessage).filter_by(folder="Work", uid="1").one_or_none()
            )

    def test_strict_archive_keeps_message_on_negative_server_result(self):
        with patch.object(mailsvc, "move_message", return_value={"ok": False}):
            response = self.client.post(
                "/api/mail/archive/A", json={"uid": "1", "folder": "Work", "require_server": True}
            )
        self.assertEqual(response.status_code, 502)
        with self.db() as db:
            self.assertEqual(db.query(CachedMessage).count(), 2)

    def test_strict_archive_removes_only_confirmed_folder(self):
        with patch.object(mailsvc, "move_message", return_value={"ok": True}) as remote:
            response = self.client.post(
                "/api/mail/archive/A", json={"uid": "1", "folder": "Work", "require_server": True}
            )
        self.assertEqual(response.json(), {"archived": 1, "moved_on_server": True})
        self.assertEqual(remote.call_args.args[1:], ("1", "Archive", "Work"))
        with self.db() as db:
            self.assertEqual([row.folder for row in db.query(CachedMessage).all()], ["INBOX"])

    def test_legacy_archive_reports_unconfirmed_server_move(self):
        with patch.object(mailsvc, "move_message", side_effect=OSError("owned failure")):
            response = self.client.post("/api/mail/archive/A", json={"uid": "1", "folder": "Work"})
        self.assertEqual(response.json(), {"archived": 1, "moved_on_server": False})
        with self.db() as db:
            self.assertEqual([row.folder for row in db.query(CachedMessage).all()], ["INBOX"])

    def test_flag_missing_message_does_not_claim_a_saved_local_change(self):
        with patch.object(mailsvc, "set_flag") as remote:
            response = self.client.post(
                "/api/mail/flag/A", params={"uid": "missing", "folder": "Work", "flagged": True}
            )
        self.assertFalse(response.json()["ok"])
        remote.assert_not_called()

    def test_read_missing_message_does_not_claim_a_saved_local_change(self):
        with patch.object(mailsvc, "set_seen") as remote:
            response = self.client.post(
                "/api/mail/read/A", params={"uid": "missing", "folder": "Work", "seen": True}
            )
        self.assertFalse(response.json()["ok"])
        remote.assert_not_called()

    def test_cache_search_preserves_folder_identity(self):
        response = self.client.get("/api/mail/cache-search/A", params={"q": "mail"})
        self.assertEqual({m.get("folder") for m in response.json()["messages"]}, {"INBOX", "Work"})


if __name__ == "__main__":
    unittest.main()

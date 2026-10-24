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
        self.assertEqual(
            response.json(), {"archived": 1, "moved_on_server": True, "message_id": ""}
        )
        self.assertEqual(remote.call_args.args[1:], ("1", "Archive", "Work"))
        with self.db() as db:
            self.assertEqual([row.folder for row in db.query(CachedMessage).all()], ["INBOX"])

    def test_legacy_archive_reports_unconfirmed_server_move(self):
        with patch.object(mailsvc, "move_message", side_effect=OSError("owned failure")):
            response = self.client.post("/api/mail/archive/A", json={"uid": "1", "folder": "Work"})
        self.assertEqual(
            response.json(), {"archived": 1, "moved_on_server": False, "message_id": ""}
        )
        with self.db() as db:
            self.assertEqual([row.folder for row in db.query(CachedMessage).all()], ["INBOX"])

    def test_archive_hands_back_the_message_id_for_undo(self):
        moved = {"ok": True, "uid": "1", "dest": "Archive", "message_id": "<a@x.test>"}
        with patch.object(mailsvc, "move_message", return_value=moved):
            response = self.client.post(
                "/api/mail/archive/A", json={"uid": "1", "folder": "Work", "require_server": True}
            )
        self.assertEqual(response.json()["message_id"], "<a@x.test>")

    def test_undo_moves_the_archived_copy_back_by_message_id(self):
        moved = {"ok": True, "uid": "9", "dest": "Work", "message_id": "<a@x.test>"}
        with patch.object(mailsvc, "move_message", return_value=moved) as remote:
            response = self.client.post(
                "/api/mail/move/A",
                json={"message_id": "<a@x.test>", "folder": "Archive", "dest": "Work"},
            )
        self.assertTrue(response.json()["moved_on_server"])
        self.assertEqual(remote.call_args.args[1:], ("", "Work", "Archive"))
        self.assertEqual(remote.call_args.kwargs, {"message_id": "<a@x.test>"})
        with self.db() as db:
            self.assertEqual(db.query(CachedMessage).count(), 2)  # nothing cached in Archive

    def test_undo_that_finds_nothing_says_so(self):
        with patch.object(mailsvc, "move_message", side_effect=LookupError("gone")):
            response = self.client.post(
                "/api/mail/move/A",
                json={"message_id": "<a@x.test>", "folder": "Archive", "dest": "Work"},
            )
        self.assertFalse(response.json()["moved_on_server"])

    def test_move_needs_a_uid_or_a_message_id(self):
        with patch.object(mailsvc, "move_message") as remote:
            response = self.client.post(
                "/api/mail/move/A", json={"folder": "Archive", "dest": "Work"}
            )
        self.assertEqual(response.status_code, 400)
        remote.assert_not_called()

    def test_flag_missing_message_does_not_claim_a_saved_local_change(self):
        with patch.object(mailsvc, "set_flag") as remote:
            response = self.client.post(
                "/api/mail/flag/A", params={"uid": "999", "folder": "Work", "flagged": True}
            )
        self.assertFalse(response.json()["ok"])
        remote.assert_not_called()

    def test_read_missing_message_does_not_claim_a_saved_local_change(self):
        with patch.object(mailsvc, "set_seen") as remote:
            response = self.client.post(
                "/api/mail/read/A", params={"uid": "999", "folder": "Work", "seen": True}
            )
        self.assertFalse(response.json()["ok"])
        remote.assert_not_called()

    def test_a_uid_or_folder_that_could_carry_an_imap_command_is_refused(self):
        # "99 (FLAGS)\r\nZZ1 CREATE x" once reached the server as a second command
        bad_uids = ["99 (FLAGS)\r\nZZ1 CREATE injected", "1 2", "1,5", "1:*", "abc", "0", "-1", ""]
        bad_folders = ["INBOX\r\nZZ2 DELETE INBOX", "Work\n", "a\u2028b"]
        calls = []
        names = ["set_flag", "set_seen", "mark_seen", "move_message", "fetch_message"]
        names += ["list_attachments", "fetch_attachment", "search"]
        patches = [
            patch.object(mailsvc, name, side_effect=lambda *a, **k: calls.append(a))
            for name in names
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        requests = []
        for uid in bad_uids:
            requests += [
                ("post", "/api/mail/flag/A", {"params": {"uid": uid, "flagged": True}}),
                ("post", "/api/mail/read/A", {"params": {"uid": uid}}),
                ("post", "/api/mail/seen/A", {"params": {"uid": uid}}),
                ("post", "/api/mail/archive/A", {"json": {"uid": uid, "require_server": True}}),
                ("get", "/api/mail/message/A", {"params": {"uid": uid}}),
                ("get", "/api/mail/attachments/A", {"params": {"uid": uid}}),
                ("get", "/api/mail/attachment/A", {"params": {"uid": uid, "index": 0}}),
            ]
            if uid:
                requests.append(
                    ("post", "/api/mail/move/A", {"json": {"uid": uid, "dest": "Work"}})
                )
        for folder in bad_folders:
            requests += [
                ("post", "/api/mail/flag/A", {"params": {"uid": "1", "folder": folder}}),
                ("post", "/api/mail/archive/A", {"json": {"uid": "1", "folder": folder}}),
                ("post", "/api/mail/move/A", {"json": {"uid": "1", "dest": folder}}),
                (
                    "post",
                    "/api/mail/move/A",
                    {"json": {"uid": "1", "folder": folder, "dest": "Work"}},
                ),
                ("get", "/api/mail/message/A", {"params": {"uid": "1", "folder": folder}}),
                ("get", "/api/mail/search/A", {"params": {"q": "x", "folder": folder}}),
            ]
        for method, url, kwargs in requests:
            with self.subTest(url=url, **kwargs):
                response = getattr(self.client, method)(url, **kwargs)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(calls, [])

    def test_inbox_threads_and_message_id_moves_refuse_before_any_connection(self):
        requests = [
            ("get", "/api/mail/inbox/A", {"params": {"folder": "INBOX\r\nZZ1 LOGOUT"}}),
            ("get", "/api/mail/inbox/A", {"params": {"folder": "a b", "quick": True}}),
            ("get", "/api/mail/threads/A", {"params": {"folder": "x\x85"}}),
            ("post", "/api/mail/move/A", {"json": {"message_id": "<a\r\nb>", "dest": "Work"}}),
            ("post", "/api/mail/move/A", {"json": {"message_id": "<ü@x>", "dest": "Work"}}),
            ("post", "/api/mail/move/A", {"json": {"message_id": "x" * 999, "dest": "Work"}}),
        ]
        with patch.object(mailsvc, "_imap") as connect:
            for method, url, kwargs in requests:
                with self.subTest(url=url, **kwargs):
                    response = getattr(self.client, method)(url, **kwargs)
                    self.assertEqual(response.status_code, 400, response.text)
        connect.assert_not_called()

    def test_account_text_that_reaches_login_cannot_hold_line_breaks(self):
        for field in ["email", "username", "password", "imap_host", "smtp_host"]:
            with self.subTest(field=field):
                response = self.client.patch(
                    "/api/mail/accounts/A", json={field: "me\r\nA1 LOGOUT"}
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn("A1 LOGOUT", response.text)
        # a tab is legal inside a quoted login; NUL isn't, nor is a tab in a host name
        self.assertEqual(
            self.client.patch("/api/mail/accounts/A", json={"password": "p\tw"}).status_code, 200
        )
        for field, value in [("password", "p\x00w"), ("imap_host", "imap\t.x")]:
            with self.subTest(field=field):
                response = self.client.patch("/api/mail/accounts/A", json={field: value})
                self.assertEqual(response.status_code, 400, response.text)

    def test_search_text_with_a_line_break_is_refused(self):
        with patch.object(mailsvc, "_imap") as connect:
            response = self.client.get(
                "/api/mail/search/A", params={"q": "hello\r\nZZ1 CREATE injected"}
            )
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()

    def test_cache_search_preserves_folder_identity(self):
        response = self.client.get("/api/mail/cache-search/A", params={"q": "mail"})
        self.assertEqual({m.get("folder") for m in response.json()["messages"]}, {"INBOX", "Work"})


if __name__ == "__main__":
    unittest.main()

"""stage 2h - IMAP folder ops (move/copy/soft-delete) against a fake IMAP. tests first (RED)."""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import mail as mailsvc


class FakeIMAP:
    def __init__(self, has_move=False, has_uidplus=False):
        self.calls = []
        caps = ["IMAP4REV1"]
        if has_move:
            caps.append("MOVE")
        if has_uidplus:
            caps.append("UIDPLUS")
        self._caps = tuple(caps)

    @property
    def capabilities(self):
        return self._caps

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder))
        return ("OK", [b"1"])

    def uid(self, cmd, *args):
        self.calls.append(
            ("uid", cmd.lower(), *[a.decode() if isinstance(a, bytes) else a for a in args])
        )
        return ("OK", [b""])

    def expunge(self):
        self.calls.append(("expunge",))
        return ("OK", [b""])


class DoMoveTests(unittest.TestCase):
    def test_uses_uid_move_when_capable(self):
        M = FakeIMAP(has_move=True)
        mailsvc._do_move(M, "42", "Archive", "INBOX")
        cmds = [c for c in M.calls if c[0] == "uid"]
        self.assertEqual(cmds[0][1], "move")
        self.assertNotIn("expunge", [c[0] for c in M.calls])

    def test_falls_back_to_copy_delete_expunge(self):
        M = FakeIMAP(has_move=False)
        mailsvc._do_move(M, "42", "Archive", "INBOX")
        kinds = [c[1] for c in M.calls if c[0] == "uid"]
        self.assertIn("copy", kinds)
        self.assertIn("store", kinds)
        self.assertIn(("expunge",), M.calls)

    def test_uidplus_scopes_expunge_to_the_one_uid(self):
        # with UIDPLUS, expunge only this uid — a plain EXPUNGE would purge every other
        # \Deleted message the user flagged in the folder
        M = FakeIMAP(has_move=False, has_uidplus=True)
        mailsvc._do_move(M, "42", "Archive", "INBOX")
        self.assertIn(("uid", "expunge", "42"), M.calls)  # scoped UID EXPUNGE
        self.assertNotIn(("expunge",), M.calls)            # not the folder-wide expunge

    def test_selects_source_first(self):
        M = FakeIMAP()
        mailsvc._do_move(M, "42", "Archive", "Work")
        self.assertEqual(M.calls[0], ("select", "Work"))

    def test_copy_targets_dest(self):
        M = FakeIMAP(has_move=False)
        mailsvc._do_move(M, "7", "Trash", "INBOX")
        copy = next(c for c in M.calls if c[0] == "uid" and c[1] == "copy")
        self.assertIn("Trash", copy)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeIMAP(has_move=True)
        self.released = []
        self._oi = mailsvc._imap
        self._or = mailsvc._release_imap
        mailsvc._imap = lambda acct: self.fake
        mailsvc._release_imap = lambda acct, M, ok=True: self.released.append(ok)

    def tearDown(self):
        mailsvc._imap = self._oi
        mailsvc._release_imap = self._or

    def test_move_message_ok_and_releases(self):
        out = mailsvc.move_message({}, "42", "Archive", "INBOX")
        self.assertTrue(out["ok"])
        self.assertEqual(out["dest"], "Archive")
        self.assertEqual(self.released, [True])

    def test_move_message_bytes_uid(self):
        out = mailsvc.move_message({}, b"99", "Archive", "INBOX")
        self.assertTrue(out["ok"])

    def test_copy_message(self):
        mailsvc.copy_message({}, "5", "Saved", "INBOX")
        self.assertTrue(any(c[0] == "uid" and c[1] == "copy" for c in self.fake.calls))
        self.assertEqual(self.released, [True])

    def test_delete_message_flags_and_expunges(self):
        mailsvc.delete_message({}, "5", "INBOX")
        kinds = [c[1] for c in self.fake.calls if c[0] == "uid"]
        self.assertIn("store", kinds)
        self.assertIn(("expunge",), self.fake.calls)

    def test_move_release_marks_failure_on_error(self):
        def boom(folder, readonly=False):
            raise OSError("connection dropped")

        self.fake.select = boom
        with self.assertRaises(OSError):
            mailsvc.move_message({}, "1", "Archive", "INBOX")
        self.assertEqual(self.released, [False])  # released with ok=False


if __name__ == "__main__":
    unittest.main()

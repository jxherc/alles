"""stage 2h - IMAP folder ops (move/copy/soft-delete) against a fake IMAP. tests first (RED)."""

import os
import re
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
        self.assertNotIn(("expunge",), M.calls)  # not the folder-wide expunge

    def test_selects_source_first(self):
        M = FakeIMAP()
        mailsvc._do_move(M, "42", "Archive", "Work")
        self.assertEqual(M.calls[0], ("select", '"Work"'))

    def test_copy_targets_dest(self):
        M = FakeIMAP(has_move=False)
        mailsvc._do_move(M, "7", "Trash", "INBOX")
        copy = next(c for c in M.calls if c[0] == "uid" and c[1] == "copy")
        self.assertIn('"Trash"', copy)


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


class ArchiveUndoIMAP(FakeIMAP):
    """answers the Message-ID header fetch and the HEADER search an archive undo needs."""

    def __init__(self, found=b"3 9 7"):
        super().__init__(has_move=True)
        self.found = found

    def uid(self, cmd, *args):
        super().uid(cmd, *args)
        if cmd.lower() == "fetch":
            return (
                "OK",
                [
                    (
                        b"1 (UID 42 BODY[HEADER.FIELDS (MESSAGE-ID)] {24}",
                        b"Message-ID: <a@x.test>\r\n\r\n",
                    ),
                    b")",
                ],
            )
        if cmd.lower() == "search":
            return ("OK", [self.found])
        return ("OK", [b""])


class MoveByMessageIdTests(unittest.TestCase):
    def setUp(self):
        self.released = []
        self._oi = mailsvc._imap
        self._or = mailsvc._release_imap
        mailsvc._release_imap = lambda acct, M, ok=True: self.released.append(ok)

    def tearDown(self):
        mailsvc._imap = self._oi
        mailsvc._release_imap = self._or
        with mailsvc._LOCK:
            mailsvc._LIST_CACHE.clear()
            mailsvc._LAST_LIST.clear()
            mailsvc._LAST_SIG.clear()

    def use(self, fake):
        mailsvc._imap = lambda acct: fake
        return fake

    def test_move_reports_the_message_id_it_read_before_moving(self):
        fake = self.use(ArchiveUndoIMAP())
        out = mailsvc.move_message({}, "42", "Archive", "INBOX")
        self.assertEqual(out["message_id"], "<a@x.test>")
        kinds = [c[1] for c in fake.calls if c[0] == "uid"]
        self.assertLess(kinds.index("fetch"), kinds.index("move"))

    def test_no_uid_moves_the_newest_match_back(self):
        # the archive just gave the message a new uid; the copy that arrived last is it
        fake = self.use(ArchiveUndoIMAP())
        out = mailsvc.move_message({}, "", "INBOX", "Archive", message_id='<a"b\\c@x.test>')
        search = next(c for c in fake.calls if c[0] == "uid" and c[1] == "search")
        self.assertEqual(search[-1], '"<a\\"b\\\\c@x.test>"')  # quoted, never bare
        self.assertIn(("uid", "move", "9", '"INBOX"'), fake.calls)
        self.assertEqual(out["uid"], "9")
        self.assertIn(("select", '"Archive"'), fake.calls)

    def test_a_message_id_that_could_break_the_command_is_refused(self):
        for bad in ["", "<a b@x>", "<a@x>\r\nA1 LOGOUT", "<é@x>"]:
            with self.subTest(bad=bad):
                fake = self.use(ArchiveUndoIMAP())
                with self.assertRaises(ValueError):
                    mailsvc.move_message({}, "", "INBOX", "Archive", message_id=bad)
                self.assertEqual([c for c in fake.calls if c[0] == "uid"], [])

    def test_nothing_found_moves_nothing(self):
        fake = self.use(ArchiveUndoIMAP(found=b""))
        with self.assertRaises(LookupError):
            mailsvc.move_message({}, "", "INBOX", "Archive", message_id="<gone@x.test>")
        self.assertNotIn("move", [c[1] for c in fake.calls if c[0] == "uid"])

    def test_a_move_drops_both_folders_cached_lists(self):
        # a refresh inside the list cache's ttl showed the archived mail again, and missed it after undo
        self.use(ArchiveUndoIMAP())
        acct = {"imap_host": "imap.test", "username": "me"}
        key = mailsvc._acct_key(acct)
        with mailsvc._LOCK:
            for folder in ["INBOX", "Archive", "Work"]:
                mailsvc._LIST_CACHE[(key, folder, 30)] = (0, [])
                mailsvc._LAST_LIST[(key, folder, 30)] = []
        mailsvc.move_message(acct, "42", "Archive", "INBOX")
        self.assertEqual([k[1] for k in mailsvc._LIST_CACHE], ["Work"])
        self.assertEqual([k[1] for k in mailsvc._LAST_LIST], ["Work"])


class CommandInjectionTests(unittest.TestCase):
    """a uid, folder or search text from a request never becomes a second IMAP command."""

    BAD_UIDS = ["99 (FLAGS)\r\nZZ1 CREATE injected", "1 2", "1,5", "1:*", "4a", "0", "", " 7"]
    BAD_FOLDERS = ["INBOX\r\nZZ2 DELETE INBOX", "Work\n", "a\u2028b", "a\x85b", "a\x9bb", ""]

    def setUp(self):
        self.opened = []
        self._oi, self._or = mailsvc._imap, mailsvc._release_imap
        self.fake = FakeIMAP(has_move=True)
        self.fake.literal = None

        def connect(acct):
            self.opened.append(acct)
            return self.fake

        mailsvc._imap = connect
        mailsvc._release_imap = lambda acct, M, ok=True: None

    def tearDown(self):
        mailsvc._imap, mailsvc._release_imap = self._oi, self._or

    def test_uids_are_plain_digits(self):
        self.assertEqual(mailsvc.message_uid("42"), b"42")
        self.assertEqual(mailsvc.message_uid(b"4294967295"), b"4294967295")
        for bad in self.BAD_UIDS + ["12345678901"]:
            with self.subTest(uid=bad), self.assertRaises(ValueError):
                mailsvc.message_uid(bad)

    def test_bad_uid_is_refused_before_a_connection_opens(self):
        calls = [
            lambda uid: mailsvc.move_message({}, uid, "Archive", "INBOX"),
            lambda uid: mailsvc.set_seen({}, uid, True),
            lambda uid: mailsvc.set_flag({}, uid, True),
            lambda uid: mailsvc.mark_seen({}, uid),
            lambda uid: mailsvc.delete_message({}, uid),
            lambda uid: mailsvc.fetch_message({}, uid, refresh=True),
            lambda uid: mailsvc.list_attachments({}, uid),
            lambda uid: mailsvc.fetch_attachment({}, uid, 0),
        ]
        for bad in [u for u in self.BAD_UIDS if u]:
            for call in calls:
                with self.subTest(uid=bad), self.assertRaises(ValueError):
                    call(bad)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.fake.calls, [])

    def test_bad_folder_is_refused_before_a_connection_opens(self):
        for bad in self.BAD_FOLDERS:
            for call in [
                lambda f: mailsvc.move_message({}, "1", f, "INBOX"),
                lambda f: mailsvc.move_message({}, "1", "Archive", f),
                lambda f: mailsvc.set_flag({}, "1", True, f),
                lambda f: mailsvc.search({}, "hello", f),
            ]:
                with self.subTest(folder=bad), self.assertRaises(ValueError):
                    call(bad)
        self.assertEqual(self.opened, [])

    def test_do_move_on_an_open_connection_also_checks(self):
        with self.assertRaises(ValueError):
            mailsvc._do_move(self.fake, "1\r\nZZ1 LOGOUT", "Archive", "INBOX")
        with self.assertRaises(ValueError):
            mailsvc._do_move(self.fake, "1", "Archive\r\nZZ1 LOGOUT", "INBOX")
        self.assertEqual(self.fake.calls, [])

    def test_search_text_is_one_quoted_string(self):
        mailsvc.search({}, 'say "hi" \\ bye')
        search = next(c for c in self.fake.calls if c[0] == "uid" and c[1] == "search")
        self.assertEqual(search[2:], (None, "TEXT", '"say \\"hi\\" \\\\ bye"'))

    def test_text_beyond_ascii_goes_as_a_counted_literal(self):
        sent = []
        uid = self.fake.uid

        def record(cmd, *args):
            sent.append(self.fake.literal)
            return uid(cmd, *args)

        self.fake.uid = record
        mailsvc.search({}, "收据")
        search = next(c for c in self.fake.calls if c[0] == "uid" and c[1] == "search")
        self.assertEqual(search[2:], ("CHARSET", "UTF-8", "TEXT"))
        self.assertEqual(sent[0], "收据".encode())
        self.assertIsNone(self.fake.literal)

    def test_search_text_with_a_line_break_never_connects(self):
        for bad in ["hello\r\nZZ1 CREATE injected", "a\nb", "tab\there"]:
            with self.subTest(text=bad), self.assertRaises(ValueError):
                mailsvc.search({}, bad)
        self.assertEqual(self.opened, [])


class MailboxWireTests(unittest.TestCase):
    """every folder goes out as one quoted string; names beyond ascii as modified UTF-7."""

    def setUp(self):
        self._oi, self._or = mailsvc._imap, mailsvc._release_imap
        self.fake = FakeIMAP(has_move=True)
        mailsvc._imap = lambda acct: self.fake
        mailsvc._release_imap = lambda acct, M, ok=True: None

    def tearDown(self):
        mailsvc._imap, mailsvc._release_imap = self._oi, self._or
        with mailsvc._LOCK:
            mailsvc._LIST_CACHE.clear()
            mailsvc._LAST_LIST.clear()

    def test_names_with_spaces_and_quotes_stay_one_argument(self):
        mailsvc.move_message({}, "7", "Sent Messages", 'IN"BOX\\x')
        self.assertIn(("select", '"IN\\"BOX\\\\x"'), self.fake.calls)
        self.assertIn(("uid", "move", "7", '"Sent Messages"'), self.fake.calls)
        mailsvc.set_flag({}, "7", True, "[Gmail]/All Mail")
        self.assertIn(("select", '"[Gmail]/All Mail"'), self.fake.calls)

    def test_listed_names_pass_as_they_are_and_unicode_names_are_encoded(self):
        self.assertEqual(mailsvc.mailbox_name("Entw&APw-rfe"), "Entw&APw-rfe")  # as LIST gives it
        self.assertEqual(mailsvc.mailbox_name("a&-b"), "a&-b")  # wire for "a&b"
        self.assertEqual(mailsvc.mailbox_name("Entwürfe"), "Entw&APw-rfe")
        # the RFC 3501 example
        self.assertEqual(
            mailsvc.mailbox_name("~peter/mail/台北/日本語"), "~peter/mail/&U,BTFw-/&ZeVnLIqe-"
        )
        self.assertEqual(mailsvc.mailbox_name("Ünï & co"), "&ANw-n&AO8- &- co")
        mailsvc.search({}, "hello", "收件箱")
        selects = [c for c in self.fake.calls if c[0] == "select"]
        self.assertTrue(all(arg.isascii() for _, arg in selects))

    def test_an_ascii_name_is_a_wire_name_only_if_it_is_canonical_modified_utf7(self):
        # a bare & isn't modified UTF-7: strict servers (dovecot) refuse it, so it's encoded
        for plain, wire in [
            ("R&D", "R&-D"),
            ("x&Y", "x&-Y"),
            ("&", "&-"),
            ("&AGE-", "&-AGE-"),  # decodes to "a", which nobody would encode that way
            ("&-", "&-"),
            ("Entw&APw-rfe", "Entw&APw-rfe"),
            ("&ZeVnLIqe-", "&ZeVnLIqe-"),
        ]:
            with self.subTest(plain=plain):
                self.assertEqual(mailsvc.mailbox_name(plain), wire)
        mailsvc.move_message({}, "2", "R&D", "INBOX")
        self.assertIn(("uid", "move", "2", '"R&-D"'), self.fake.calls)

    def test_search_folder_and_move_by_message_id_refuse_before_connecting(self):
        opened = []
        mailsvc._imap = lambda acct: opened.append(acct) or self.fake
        for bad in ["<a b>", "<a\tb>", "<ü@x>", "", "x" * 999]:
            with self.subTest(mid=bad), self.assertRaises(ValueError):
                mailsvc.move_message({}, "", "INBOX", "Archive", message_id=bad)
        with self.assertRaises(ValueError):
            mailsvc.fetch_inbox({}, "INBOX\r\nZZ1 LOGOUT")
        self.assertEqual(opened, [])


class ListFoldersTests(unittest.TestCase):
    """LIST names come back exactly as the server named them, whatever shape the line has."""

    LINES = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        b'(\\HasNoChildren) "/" "Sent \\"x\\""',
        b'(\\HasNoChildren) "/" "a\\\\b"',
        (b'(\\HasNoChildren) "/" {5}', b"hello"),
        b"",
        b'(\\HasNoChildren) NIL "Entw&APw-rfe"',
        b'(\\HasNoChildren) "/" a&-b',
        b'(\\HasNoChildren) "." INBOX.Sent',
        b"(\\HasNoChildren) NIL Archive",
        b'(\\HasNoChildren) "/" "trailing \\\\"',
    ]
    NAMES = ["INBOX", "[Gmail]/All Mail", 'Sent "x"', "a\\b", "hello", "Entw&APw-rfe", "a&-b"]
    NAMES += ["INBOX.Sent", "Archive", "trailing \\"]

    class Server(FakeIMAP):
        def list(self):
            return "OK", ListFoldersTests.LINES

    def setUp(self):
        self._oi, self._or = mailsvc._imap, mailsvc._release_imap
        self.fake = self.Server()
        mailsvc._imap = lambda acct: self.fake
        mailsvc._release_imap = lambda acct, M, ok=True: None

    def tearDown(self):
        mailsvc._imap, mailsvc._release_imap = self._oi, self._or

    def test_every_shape_comes_back_as_the_server_named_it(self):
        self.assertEqual(mailsvc.list_folders({}), self.NAMES)

    def test_a_listed_name_selects_that_same_mailbox(self):
        # the round trip: LIST -> the UI -> SELECT; the server unquotes back to its own name
        def unquote(arg):
            self.assertTrue(arg.startswith('"') and arg.endswith('"'), arg)
            return re.sub(r"\\(.)", r"\1", arg[1:-1])

        for name in mailsvc.list_folders({}):
            with self.subTest(name=name):
                self.fake.calls.clear()
                mailsvc.set_flag({}, "1", True, name)
                selected = unquote(self.fake.calls[0][1])
                self.assertEqual(selected, name)
                self.assertIsNotNone(mailsvc._utf7_imap_decode(selected))


class LoginTests(unittest.TestCase):
    """LOGIN: the username goes quoted (imaplib quotes only the password), and a line break in
    either never reaches the server."""

    class Server:
        def __init__(self):
            self.calls = []

        def login(self, user, password):
            self.calls.append(("login", user, password))

        def logout(self):
            pass

    def setUp(self):
        self._open = mailsvc._open_imap
        self.server = self.Server()
        self.opened = []
        mailsvc._open_imap = lambda acct: self.opened.append(acct) or self.server
        with mailsvc._LOCK:
            mailsvc._POOL.clear()

    def tearDown(self):
        mailsvc._open_imap = self._open

    def test_username_is_quoted(self):
        mailsvc._imap({"imap_host": "h", "username": 'me "x"', "password": "pw"})
        self.assertEqual(self.server.calls, [("login", '"me \\"x\\""', "pw")])

    def test_control_characters_never_reach_login(self):
        for acct in [
            {"imap_host": "h", "username": "me\r\nA1 LOGOUT", "password": "pw"},
            {"imap_host": "h", "username": "me", "password": "pw\r\nA1 LOGOUT"},
            {"imap_host": "h", "email": "me\n@x", "password": "pw"},
            {"imap_host": "h", "username": "mé", "password": "pw"},
            {"imap_host": "h", "username": "me", "password": "pw\x00"},
        ]:
            with self.subTest(acct=acct), self.assertRaises(ValueError) as caught:
                mailsvc._imap(acct)
            self.assertNotIn("codec", str(caught.exception))
        self.assertEqual(self.opened, [])

    def test_a_tab_is_legal_in_a_quoted_login(self):
        mailsvc._imap({"imap_host": "h", "username": "me\tx", "password": "p\tw"})
        self.assertEqual(self.server.calls, [("login", '"me\tx"', "p\tw")])


class ImapPoolTests(unittest.TestCase):
    def tearDown(self):
        with mailsvc._LOCK:
            mailsvc._POOL.clear()

    def test_release_logs_out_replaced_connection_after_unlock(self):
        acct = {"imap_host": "imap.test", "imap_port": 993, "username": "me", "use_ssl": True}

        class Probe:
            lock_was_free = None

            def logout(self):
                self.lock_was_free = mailsvc._LOCK.acquire(blocking=False)
                if self.lock_was_free:
                    mailsvc._LOCK.release()

        old = Probe()
        new = Probe()
        key = mailsvc._acct_key(acct)
        with mailsvc._LOCK:
            mailsvc._POOL[key] = (old, 0)

        mailsvc._release_imap(acct, new, ok=True)

        self.assertTrue(old.lock_was_free)
        self.assertIs(mailsvc._POOL[key][0], new)


if __name__ == "__main__":
    unittest.main()

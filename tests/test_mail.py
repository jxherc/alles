import unittest

from services import mail


class MailHelperTests(unittest.TestCase):
    def test_decode_header(self):
        self.assertEqual(mail._dec("=?utf-8?q?hello_world?="), "hello world")
        self.assertEqual(mail._dec("plain subject"), "plain subject")
        self.assertEqual(mail._dec(""), "")

    def test_payload_decodes_text(self):
        from email.message import EmailMessage

        m = EmailMessage()
        m.set_content("body text here")
        # the text/plain part
        part = list(m.walk())[-1] if m.is_multipart() else m
        self.assertIn("body text", mail._payload(part))

    def test_missing_imap_host_raises(self):
        with self.assertRaises(ValueError):
            mail._imap({"imap_host": ""})

    def test_missing_smtp_host_raises(self):
        with self.assertRaises(ValueError):
            mail.send_mail({"smtp_host": ""}, "x@y.com", "subj", "body")


class BuildMessageTests(unittest.TestCase):
    def test_reply_headers(self):
        m = mail._build_message(
            {"email": "me@x.com"},
            "you@y.com",
            "Re: hi",
            "body",
            in_reply_to="<abc@y.com>",
            references="<root@y.com>",
        )
        self.assertEqual(m["In-Reply-To"], "<abc@y.com>")
        # references chain keeps the root then appends the parent
        self.assertEqual(m["References"], "<root@y.com> <abc@y.com>")

    def test_reply_without_prior_references(self):
        m = mail._build_message(
            {"email": "me@x.com"}, "you@y.com", "Re: hi", "b", in_reply_to="<abc@y.com>"
        )
        self.assertEqual(m["References"], "<abc@y.com>")

    def test_bcc_and_cc_set(self):
        m = mail._build_message(
            {"email": "me@x.com"}, "a@x.com", "s", "b", cc="c@x.com", bcc="d@x.com"
        )
        self.assertEqual(m["Cc"], "c@x.com")
        self.assertEqual(m["Bcc"], "d@x.com")

    def test_plain_message_has_no_reply_headers(self):
        m = mail._build_message({"email": "me@x.com"}, "a@x.com", "s", "b")
        self.assertIsNone(m["In-Reply-To"])
        self.assertIsNone(m["References"])


class ThreadKeyTests(unittest.TestCase):
    def test_normalize_strips_prefixes(self):
        self.assertEqual(mail.normalize_subject("Re: Fwd: Hello"), "Hello")
        self.assertEqual(mail.normalize_subject("AW: WG: Test"), "Test")
        self.assertEqual(mail.normalize_subject(""), "(no subject)")

    def test_group_threads_collapses(self):
        msgs = [
            {"uid": "1", "subject": "Project plan", "date_ts": 100, "seen": True, "from": "a@x"},
            {
                "uid": "2",
                "subject": "Re: Project plan",
                "date_ts": 200,
                "seen": False,
                "from": "b@x",
            },
            {"uid": "3", "subject": "Lunch?", "date_ts": 150, "seen": True, "from": "c@x"},
        ]
        threads = mail.group_threads(msgs)
        self.assertEqual(len(threads), 2)
        top = threads[0]  # newest-latest first → the Project plan thread (ts 200)
        self.assertEqual(top["count"], 2)
        self.assertEqual(top["unseen"], 1)
        self.assertEqual(top["uid"], "2")


if __name__ == "__main__":
    unittest.main()

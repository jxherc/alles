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


if __name__ == "__main__":
    unittest.main()

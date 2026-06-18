import unittest
from email.message import EmailMessage

from services import mail as m


class SubjectTests(unittest.TestCase):
    def test_strips_reply_prefixes(self):
        self.assertEqual(m.normalize_subject("Re: Hello"), "Hello")
        self.assertEqual(m.normalize_subject("FWD: stuff"), "stuff")
        self.assertEqual(m.normalize_subject("RE: Fw: Re: deep"), "deep")
        self.assertEqual(m.normalize_subject("plain"), "plain")

    def test_empty(self):
        self.assertEqual(m.normalize_subject(""), "(no subject)")


class ThreadTests(unittest.TestCase):
    def test_groups_by_normalized_subject(self):
        msgs = [
            {"uid": "1", "subject": "Project X", "date_ts": 100, "seen": True, "from": "a"},
            {"uid": "2", "subject": "Re: Project X", "date_ts": 200, "seen": False, "from": "b"},
            {"uid": "3", "subject": "Lunch", "date_ts": 150, "seen": True, "from": "c"},
        ]
        threads = m.group_threads(msgs)
        self.assertEqual(len(threads), 2)
        # newest-activity thread first
        self.assertEqual(threads[0]["subject"], "Project X")
        self.assertEqual(threads[0]["count"], 2)
        self.assertEqual(threads[0]["unseen"], 1)
        self.assertEqual(threads[0]["uid"], "2")  # latest message in the thread
        self.assertEqual(threads[1]["subject"], "Lunch")

    def test_empty(self):
        self.assertEqual(m.group_threads([]), [])


class AttachmentTests(unittest.TestCase):
    def _msg(self):
        msg = EmailMessage()
        msg["Subject"] = "report"
        msg.set_content("here is the report")
        msg.add_attachment(
            b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="report.pdf"
        )
        return msg

    def test_lists_attachment_only(self):
        atts = m.attachments_of(self._msg())
        self.assertEqual(len(atts), 1)  # body text isn't an attachment
        self.assertEqual(atts[0]["filename"], "report.pdf")
        self.assertEqual(atts[0]["content_type"], "application/pdf")
        self.assertEqual(atts[0]["size"], len(b"%PDF-1.4 fake"))

    def test_plain_message_has_none(self):
        msg = EmailMessage()
        msg.set_content("just text")
        self.assertEqual(m.attachments_of(msg), [])


if __name__ == "__main__":
    unittest.main()

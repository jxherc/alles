import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import MailAccount
from services import mail as mailsvc
from services import mail_compose
from tests._client import ApiTest

ACCT = {"email": "me@x.com", "username": "me@x.com"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def _types(msg):
    return [p.get_content_type() for p in msg.walk()]


class BuildMimeTests(ApiTest):
    def test_build_plain_only(self):
        msg = mailsvc._build_message(ACCT, "to@x.com", "subj", "hello")
        self.assertEqual(msg.get_content_type(), "text/plain")
        self.assertNotIn("text/html", _types(msg))

    def test_build_html_alternative(self):
        msg = mailsvc._build_message(ACCT, "to@x.com", "subj", "hello", html="<b>hi</b>")
        self.assertIn("text/plain", _types(msg))
        self.assertIn("text/html", _types(msg))

    def test_build_inline_image_has_cid(self):
        msg = mailsvc._build_message(
            ACCT,
            "to@x.com",
            "s",
            "t",
            html='<img src="cid:abc">',
            inline=[{"cid": "abc", "data": PNG, "subtype": "png"}],
        )
        cids = [p.get("Content-ID", "") for p in msg.walk()]
        self.assertTrue(any("abc" in c for c in cids))
        self.assertIn("image/png", _types(msg))


class EmbedInlineTests(ApiTest):
    def test_embed_inline_rewrites_src(self):
        html, inline = mail_compose.embed_inline(
            '<p>x</p><img src="/api/uploads/u1">', lambda i: (PNG, "png")
        )
        self.assertIn("cid:u1", html)
        self.assertNotIn("/api/uploads/u1", html)
        self.assertEqual(inline[0]["cid"], "u1")

    def test_embed_inline_no_images(self):
        html, inline = mail_compose.embed_inline("<p>just text</p>", lambda i: (None, None))
        self.assertEqual(html, "<p>just text</p>")
        self.assertEqual(inline, [])

    def test_embed_inline_collects_bytes(self):
        _, inline = mail_compose.embed_inline(
            '<img src="/api/uploads/a"><img src="/api/uploads/b">', lambda i: (PNG, "png")
        )
        self.assertEqual(len(inline), 2)
        self.assertEqual(inline[0]["data"], PNG)


class SignaturesTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self._p = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        super().tearDown()

    def test_signatures_crud(self):
        s = self.client.post(
            "/api/mail/signatures", json={"name": "Work", "body": "Best,\nMe"}
        ).json()
        self.assertTrue(
            any(
                x["name"] == "Work"
                for x in self.client.get("/api/mail/signatures").json()["signatures"]
            )
        )
        self.client.delete(f"/api/mail/signatures/{s['id']}")
        self.assertFalse(self.client.get("/api/mail/signatures").json()["signatures"])

    def test_signature_update_by_id(self):
        s = self.client.post("/api/mail/signatures", json={"name": "A", "body": "x"}).json()
        self.client.post("/api/mail/signatures", json={"id": s["id"], "name": "A", "body": "y"})
        sigs = self.client.get("/api/mail/signatures").json()["signatures"]
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["body"], "y")


class ScheduledHtmlTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        a = MailAccount(
            name="Me", email="me@x.com", imap_host="i", smtp_host="s", username="me", password="p"
        )
        db.add(a)
        db.commit()
        self.aid = a.id
        db.close()

    def test_scheduled_carries_html(self):
        self.client.post(
            f"/api/mail/schedule/{self.aid}",
            json={
                "to": "b@x.com",
                "subject": "s",
                "body": "t",
                "html": "<b>hi</b>",
                "send_at": "2099-01-01T00:00:00",
            },
        )
        from core.database import ScheduledMail

        db = self.db()
        row = db.query(ScheduledMail).first()
        self.assertEqual(row.html, "<b>hi</b>")
        db.close()

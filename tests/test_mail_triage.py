from datetime import datetime, timezone

from core.database import CachedMessage, MailAccount
from services import mail as mailsvc
from services import mail_cache
from tests._client import ApiTest


def _ts(d):
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()


class MailTriageTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = MailAccount(
            name="Me",
            email="me@x.com",
            imap_host="imap.x.com",
            smtp_host="smtp.x.com",
            username="me@x.com",
            password="pw",
        )
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _msg(self, uid, sender, subject, date="2026-06-10", list_unsubscribe="", muted=False):
        db = self.db()
        db.add(
            CachedMessage(
                account_id=self.aid,
                folder="INBOX",
                uid=str(uid),
                sender=sender,
                subject=subject,
                date=date,
                date_ts=_ts(date),
                seen=False,
                list_unsubscribe=list_unsubscribe,
                muted=muted,
            )
        )
        db.commit()
        db.close()

    # ---- list-unsubscribe parsing ----
    def test_parse_unsub_http(self):
        d = mailsvc.parse_list_unsubscribe("<https://e.com/unsub?id=1>")
        self.assertEqual(d["http"], "https://e.com/unsub?id=1")
        self.assertEqual(d["mailto"], "")

    def test_parse_unsub_mailto(self):
        d = mailsvc.parse_list_unsubscribe("<mailto:unsub@e.com?subject=stop>")
        self.assertEqual(d["mailto"], "mailto:unsub@e.com?subject=stop")

    def test_parse_unsub_both(self):
        d = mailsvc.parse_list_unsubscribe("<mailto:u@e.com>, <https://e.com/u>")
        self.assertEqual(d["http"], "https://e.com/u")
        self.assertEqual(d["mailto"], "mailto:u@e.com")

    # ---- search-operator parsing ----
    def test_parse_query_operators(self):
        s = mailsvc.parse_search_query(
            "from:alice subject:invoice has:attachment before:2026-06-01 hi"
        )
        self.assertEqual(s["from"], "alice")
        self.assertEqual(s["subject"], "invoice")
        self.assertTrue(s["has_attachment"])
        self.assertEqual(s["before"], "2026-06-01")
        self.assertEqual(s["text"], "hi")

    def test_parse_query_plain_text(self):
        s = mailsvc.parse_search_query("just some words")
        self.assertEqual(s["text"], "just some words")
        self.assertEqual(s["from"], "")

    # ---- advanced cache search ----
    def test_adv_search_from(self):
        self._msg(1, "Alice <alice@x.com>", "hello")
        self._msg(2, "Bob <bob@x.com>", "hi")
        d = self.client.get(f"/api/mail/adv-search/{self.aid}", params={"q": "from:alice"}).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])

    def test_adv_search_subject(self):
        self._msg(1, "a@x.com", "June Invoice")
        self._msg(2, "b@x.com", "Lunch?")
        d = self.client.get(
            f"/api/mail/adv-search/{self.aid}", params={"q": "subject:invoice"}
        ).json()
        self.assertEqual([m["uid"] for m in d["messages"]], ["1"])

    def test_adv_search_before_after(self):
        self._msg(1, "a@x.com", "early", date="2026-06-01")
        self._msg(2, "b@x.com", "late", date="2026-06-20")
        after = self.client.get(
            f"/api/mail/adv-search/{self.aid}", params={"q": "after:2026-06-10"}
        ).json()
        self.assertEqual([m["uid"] for m in after["messages"]], ["2"])
        before = self.client.get(
            f"/api/mail/adv-search/{self.aid}", params={"q": "before:2026-06-10"}
        ).json()
        self.assertEqual([m["uid"] for m in before["messages"]], ["1"])

    # ---- mute + archive ----
    def test_mute_hides_thread(self):
        self._msg(1, "a@x.com", "Re: Project plan")
        self._msg(2, "b@x.com", "Project plan")
        self.client.post(f"/api/mail/mute/{self.aid}", json={"subject": "Project plan"})
        rows = mail_cache.get_filtered(self.db(), self.aid)
        self.assertEqual(rows, [])

    def test_archive_removes_from_cache(self):
        self._msg(1, "a@x.com", "keep")
        self._msg(2, "b@x.com", "bye")
        self.client.post(f"/api/mail/archive/{self.aid}", json={"uid": "2"})
        uids = [
            m["uid"] for m in self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        ]
        self.assertIn("1", uids)
        self.assertNotIn("2", uids)

    def test_unified_excludes_muted(self):
        self._msg(1, "a@x.com", "visible")
        self._msg(2, "b@x.com", "hidden", muted=True)
        uids = [m["uid"] for m in mail_cache.get_unified(self.db())]
        self.assertIn("1", uids)
        self.assertNotIn("2", uids)

    def test_cached_row_has_list_unsubscribe(self):
        self._msg(1, "news@x.com", "Newsletter", list_unsubscribe="<https://x.com/u>")
        msgs = self.client.get(f"/api/mail/cached/{self.aid}").json()["messages"]
        self.assertEqual(msgs[0]["list_unsubscribe"], "<https://x.com/u>")

    # ---- saved searches ----
    def test_saved_search_crud(self):
        s = self.client.post(
            "/api/mail/saved-searches", json={"name": "From boss", "query": "from:boss@x.com"}
        ).json()
        self.assertTrue(
            any(
                x["name"] == "From boss"
                for x in self.client.get("/api/mail/saved-searches").json()["searches"]
            )
        )
        self.client.delete(f"/api/mail/saved-searches/{s['id']}")
        self.assertFalse(self.client.get("/api/mail/saved-searches").json()["searches"])

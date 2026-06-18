from tests._client import ApiTest
from core.database import MailAccount
from services import mail_cache


def _msgs():
    return [
        {
            "uid": "1",
            "from": "alice@x.com",
            "subject": "Lunch plans",
            "date": "d1",
            "date_ts": 100,
            "seen": True,
        },
        {
            "uid": "2",
            "from": "bob@y.com",
            "subject": "Invoice #42",
            "date": "d2",
            "date_ts": 300,
            "seen": False,
        },
        {
            "uid": "3",
            "from": "carol@z.com",
            "subject": "re: Lunch",
            "date": "d3",
            "date_ts": 200,
            "seen": False,
        },
    ]


class MailCacheTest(ApiTest):
    def _account(self):
        d = self.db()
        a = MailAccount(name="test", email="me@x.com", imap_host="imap.x.com")
        d.add(a)
        d.commit()
        aid = a.id
        d.close()
        return aid

    def test_save_get_newest_first(self):
        d = self.db()
        mail_cache.save(d, "acct", "INBOX", _msgs())
        got = mail_cache.get(d, "acct", "INBOX")
        d.close()
        self.assertEqual([m["uid"] for m in got], ["2", "3", "1"])  # by date_ts desc
        self.assertEqual(got[0]["from"], "bob@y.com")
        self.assertTrue(got[0]["cached"])

    def test_save_replaces_folder(self):
        d = self.db()
        mail_cache.save(d, "acct", "INBOX", _msgs())
        mail_cache.save(d, "acct", "INBOX", _msgs()[:1])  # re-fetch with fewer
        self.assertEqual(len(mail_cache.get(d, "acct", "INBOX")), 1)
        d.close()

    def test_search_subject_and_sender(self):
        d = self.db()
        mail_cache.save(d, "acct", "INBOX", _msgs())
        self.assertEqual({m["uid"] for m in mail_cache.search(d, "acct", "lunch")}, {"1", "3"})
        self.assertEqual([m["uid"] for m in mail_cache.search(d, "acct", "bob")], ["2"])
        d.close()

    def test_cached_route_instant(self):
        aid = self._account()
        d = self.db()
        mail_cache.save(d, aid, "INBOX", _msgs())
        d.close()
        r = self.client.get(f"/api/mail/cached/{aid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["messages"]), 3)
        self.assertTrue(r.json()["cached"])

    def test_cache_search_route(self):
        aid = self._account()
        d = self.db()
        mail_cache.save(d, aid, "INBOX", _msgs())
        d.close()
        r = self.client.get(f"/api/mail/cache-search/{aid}", params={"q": "invoice"})
        self.assertEqual([m["uid"] for m in r.json()["messages"]], ["2"])

    def test_cached_route_unknown_account_404(self):
        self.assertEqual(self.client.get("/api/mail/cached/nope").status_code, 404)

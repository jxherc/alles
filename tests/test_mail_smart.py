from core.database import MailAccount
from services import mail_cache
from tests._client import ApiTest


def _msg(uid, subj, ts, seen=False, flagged=False):
    return {
        "uid": uid,
        "from": f"{subj}@x.com",
        "subject": subj,
        "date": "",
        "date_ts": ts,
        "seen": seen,
        "flagged": flagged,
    }


class MailSmartCacheTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.d = self.db()
        # two accounts so unified has something to merge
        for aid in ("A", "B"):
            self.d.add(MailAccount(id=aid, name=aid, email=f"{aid}@x.com", imap_host="h"))
        self.d.commit()

    def tearDown(self):
        self.d.close()
        super().tearDown()

    def test_unified_merges_newest_first(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg("1", "a1", 100), _msg("2", "a2", 300)])
        mail_cache.save(self.d, "B", "INBOX", [_msg("3", "b1", 200)])
        out = mail_cache.get_unified(self.d, limit=10)
        self.assertEqual([m["subject"] for m in out], ["a2", "b1", "a1"])

    def test_unified_includes_account(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg("1", "a1", 100)])
        out = mail_cache.get_unified(self.d, limit=10)
        self.assertEqual(out[0]["account_id"], "A")

    def test_unified_limit(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg(str(i), f"m{i}", i) for i in range(5)])
        self.assertEqual(len(mail_cache.get_unified(self.d, limit=3)), 3)

    def test_filter_unread(self):
        mail_cache.save(
            self.d, "A", "INBOX", [_msg("1", "read", 10, seen=True), _msg("2", "new", 20)]
        )
        out = mail_cache.get_filtered(self.d, "A", unread=True)
        self.assertEqual([m["subject"] for m in out], ["new"])

    def test_filter_flagged(self):
        mail_cache.save(
            self.d, "A", "INBOX", [_msg("1", "plain", 10), _msg("2", "star", 20, flagged=True)]
        )
        out = mail_cache.get_filtered(self.d, "A", flagged=True)
        self.assertEqual([m["subject"] for m in out], ["star"])

    def test_set_flag_toggles(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg("1", "x", 10)])
        mail_cache.set_flag(self.d, "A", "INBOX", "1", True)
        self.assertTrue(mail_cache.get(self.d, "A", "INBOX")[0]["flagged"])
        mail_cache.set_flag(self.d, "A", "INBOX", "1", False)
        self.assertFalse(mail_cache.get(self.d, "A", "INBOX")[0]["flagged"])

    def test_flag_survives_refetch(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg("1", "x", 10)])
        mail_cache.set_flag(self.d, "A", "INBOX", "1", True)
        # a real IMAP re-fetch yields headers with no "flagged" key — local star must persist
        refetch = {
            "uid": "1",
            "from": "x@x.com",
            "subject": "x",
            "date": "",
            "date_ts": 10,
            "seen": False,
        }
        mail_cache.save(self.d, "A", "INBOX", [refetch])
        self.assertTrue(mail_cache.get(self.d, "A", "INBOX")[0]["flagged"])

    def test_to_msg_has_flagged(self):
        mail_cache.save(self.d, "A", "INBOX", [_msg("1", "x", 10, flagged=True)])
        self.assertIn("flagged", mail_cache.get(self.d, "A", "INBOX")[0])


class MailSmartApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.d = self.db()
        self.d.add(MailAccount(id="A", name="A", email="a@x.com", imap_host="h"))
        self.d.commit()
        mail_cache.save(
            self.d, "A", "INBOX", [_msg("1", "read", 10, seen=True), _msg("2", "new", 20)]
        )

    def tearDown(self):
        self.d.close()
        super().tearDown()

    def test_api_unified(self):
        r = self.client.get("/api/mail/unified")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["messages"]), 2)

    def test_api_smart_unread(self):
        r = self.client.get("/api/mail/smart/A", params={"filter": "unread"})
        self.assertEqual([m["subject"] for m in r.json()["messages"]], ["new"])

    def test_api_flag(self):
        self.client.post(
            "/api/mail/flag/A", params={"uid": "2", "folder": "INBOX", "flagged": "true"}
        )
        flagged = [m for m in mail_cache.get(self.db(), "A", "INBOX") if m["flagged"]]
        self.assertEqual([m["subject"] for m in flagged], ["new"])

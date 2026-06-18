import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings as cs
from core.database import MailAccount
from services import mail as mailsvc
from services import mail_cache
from tests._client import ApiTest


class IsVipTests(unittest.TestCase):
    def test_named_address(self):
        self.assertTrue(mailsvc.is_vip("Mom <mom@x.com>", ["mom@x.com"]))

    def test_bare_address(self):
        self.assertTrue(mailsvc.is_vip("boss@x.com", ["boss@x.com"]))

    def test_case_insensitive(self):
        self.assertTrue(mailsvc.is_vip("Boss <BOSS@X.com>", ["boss@x.com"]))

    def test_not_listed(self):
        self.assertFalse(mailsvc.is_vip("rando@x.com", ["mom@x.com"]))

    def test_empty_list(self):
        self.assertFalse(mailsvc.is_vip("a@x.com", []))


class SeenAndVipApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._p.start()
        self.d = self.db()
        self.d.add(MailAccount(id="A", name="A", email="a@x.com", imap_host=""))
        self.d.commit()
        mail_cache.save(
            self.d,
            "A",
            "INBOX",
            [
                {
                    "uid": "1",
                    "from": "Mom <mom@x.com>",
                    "subject": "vip msg",
                    "date_ts": 30,
                    "seen": True,
                },
                {
                    "uid": "2",
                    "from": "rando@x.com",
                    "subject": "other",
                    "date_ts": 20,
                    "seen": True,
                },
            ],
        )

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()
        self.d.close()
        super().tearDown()

    def test_set_seen_cache_true_false(self):
        mail_cache.set_seen(self.d, "A", "INBOX", "1", False)
        self.assertFalse(
            [m for m in mail_cache.get(self.d, "A", "INBOX") if m["uid"] == "1"][0]["seen"]
        )
        mail_cache.set_seen(self.d, "A", "INBOX", "1", True)
        self.assertTrue(
            [m for m in mail_cache.get(self.d, "A", "INBOX") if m["uid"] == "1"][0]["seen"]
        )

    def test_api_read_marks_unread(self):
        self.client.post(
            "/api/mail/read/A", params={"uid": "1", "seen": "false", "folder": "INBOX"}
        )
        m = [x for x in mail_cache.get(self.db(), "A", "INBOX") if x["uid"] == "1"][0]
        self.assertFalse(m["seen"])

    def test_api_read_marks_read(self):
        mail_cache.set_seen(self.d, "A", "INBOX", "1", False)
        self.client.post("/api/mail/read/A", params={"uid": "1", "seen": "true", "folder": "INBOX"})
        m = [x for x in mail_cache.get(self.db(), "A", "INBOX") if x["uid"] == "1"][0]
        self.assertTrue(m["seen"])

    def test_vip_add_list_remove(self):
        self.client.post("/api/mail/vips", json={"email": "mom@x.com", "add": True})
        self.assertIn("mom@x.com", self.client.get("/api/mail/vips").json()["vips"])
        self.client.post("/api/mail/vips", json={"email": "mom@x.com", "add": False})
        self.assertNotIn("mom@x.com", self.client.get("/api/mail/vips").json()["vips"])

    def test_smart_vip_filter(self):
        self.client.post("/api/mail/vips", json={"email": "mom@x.com", "add": True})
        r = self.client.get("/api/mail/smart/A", params={"filter": "vip"})
        self.assertEqual([m["subject"] for m in r.json()["messages"]], ["vip msg"])


if __name__ == "__main__":
    unittest.main()

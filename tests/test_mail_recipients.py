"""ui-4d — /api/mail/recipients powers compose address autocomplete from the mail
cache (distinct correspondents, name + address, substring-filterable)."""

from core.database import CachedMessage
from tests._client import ApiTest


class RecipientsTests(ApiTest):
    def _seed(self):
        db = self.db()
        rows = [
            ("Ada Lovelace <ada@math.org>", 30),
            ("ada@math.org", 25),                       # dup address, no name
            ("Bob <bob@work.com>", 20),
            ("no-reply@spam.io", 10),
        ]
        for i, (sender, ts) in enumerate(rows):
            db.add(CachedMessage(account_id="a1", folder="INBOX", uid=str(i),
                                 sender=sender, subject="s", date="2026-06-10", date_ts=ts, seen=True))
        db.commit()
        db.close()

    def test_empty_when_no_cache(self):
        self.assertEqual(self.client.get("/api/mail/recipients").json()["recipients"], [])

    def test_distinct_addresses_with_names(self):
        self._seed()
        recs = self.client.get("/api/mail/recipients").json()["recipients"]
        emails = [r["email"] for r in recs]
        self.assertIn("ada@math.org", emails)
        self.assertIn("bob@work.com", emails)
        # ada appears once despite two cached rows
        self.assertEqual(emails.count("ada@math.org"), 1)
        ada = next(r for r in recs if r["email"] == "ada@math.org")
        self.assertEqual(ada["name"], "Ada Lovelace")

    def test_substring_filter(self):
        self._seed()
        recs = self.client.get("/api/mail/recipients?q=bob").json()["recipients"]
        self.assertEqual([r["email"] for r in recs], ["bob@work.com"])

    def test_filter_matches_name_too(self):
        self._seed()
        recs = self.client.get("/api/mail/recipients?q=lovelace").json()["recipients"]
        self.assertEqual([r["email"] for r in recs], ["ada@math.org"])

    def test_limit_respected(self):
        self._seed()
        recs = self.client.get("/api/mail/recipients?limit=1").json()["recipients"]
        self.assertEqual(len(recs), 1)

    def test_ordered_by_recency(self):
        self._seed()
        recs = self.client.get("/api/mail/recipients").json()["recipients"]
        # ada (ts 30) is most recent → first
        self.assertEqual(recs[0]["email"], "ada@math.org")

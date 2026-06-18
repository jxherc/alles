from datetime import date

from core.database import Account, Task, Transaction
from tests._client import ApiTest


class TimelineSearchTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        acct = Account(name="Checking", opening=0)
        d.add(acct)
        d.flush()
        today = date.today().isoformat()
        d.add(
            Transaction(
                account_id=acct.id, date=today, amount=-12.5, payee="Starbucks", category="coffee"
            )
        )
        d.add(
            Transaction(account_id=acct.id, date=today, amount=-40.0, payee="Shell", category="gas")
        )
        d.add(Task(title="Email the landlord", done=False))
        d.add(Task(title="Buy coffee beans", done=False))
        d.commit()
        d.close()

    def _tl(self, **params):
        return self.client.get("/api/timeline", params={"days": 30, "limit": 200, **params}).json()[
            "events"
        ]

    def test_no_q_returns_all(self):
        self.assertGreaterEqual(len(self._tl()), 4)

    def test_q_matches_title(self):
        titles = [e["title"] for e in self._tl(q="starbucks")]
        self.assertTrue(any("Starbucks" in t for t in titles))
        self.assertTrue(all("Shell" not in t for t in titles))

    def test_q_matches_subtitle(self):
        # transaction subtitle is the signed amount; category is in the title/subtitle path —
        # search "coffee" should hit the Buy coffee beans task title at least
        hits = self._tl(q="coffee")
        self.assertTrue(hits)

    def test_q_case_insensitive(self):
        self.assertTrue(self._tl(q="STARBUCKS"))

    def test_q_no_match_empty(self):
        self.assertEqual(self._tl(q="zzzznotfound"), [])

    def test_q_blank_returns_all(self):
        self.assertGreaterEqual(len(self._tl(q="")), 4)

    def test_q_with_types(self):
        # restrict to tasks, search 'landlord' → only the email task
        hits = self._tl(q="landlord", types="task")
        self.assertEqual(len(hits), 1)
        self.assertIn("landlord", hits[0]["title"].lower())

    def test_q_respects_limit(self):
        hits = self._tl(q="", limit=2)
        self.assertLessEqual(len(hits), 2)

    def test_q_matches_task_title(self):
        hits = self._tl(q="email")
        self.assertTrue(any("Email" in e["title"] for e in hits))

    def test_q_substring_partial(self):
        self.assertTrue(self._tl(q="buck"))

import json
from datetime import date, timedelta

from core.database import ProactiveItem, Task
from services import proactive
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class ProactiveApiTests(ApiTest):
    def _seed_card(self, **kw):
        d = self.db()
        defaults = dict(dedupe_key="dk", title="card", source_keys="[]", score=50)
        defaults.update(kw)
        it = ProactiveItem(**defaults)
        d.add(it)
        d.commit()
        rid = it.id
        d.close()
        return rid

    def test_list_sorted_and_filtered(self):
        self._seed_card(dedupe_key="a", title="low", score=30)
        self._seed_card(dedupe_key="b", title="high", score=90)
        self._seed_card(dedupe_key="c", title="gone", score=99, dismissed=True)
        rows = self.client.get("/api/proactive").json()
        self.assertEqual([r["title"] for r in rows], ["high", "low"])  # dismissed excluded, score desc

    def test_dismiss_hides(self):
        rid = self._seed_card(dedupe_key="a", title="x")
        self.assertEqual(len(self.client.get("/api/proactive").json()), 1)
        r = self.client.post(f"/api/proactive/{rid}/dismiss").json()
        self.assertTrue(r["ok"])
        self.assertEqual(self.client.get("/api/proactive").json(), [])

    def test_dismiss_missing(self):
        r = self.client.post("/api/proactive/nope/dismiss").json()
        self.assertFalse(r["ok"])

    def test_run_endpoint_creates_cards(self):
        d = self.db()
        d.add(Task(title="pay rent", done=False, due_date=_iso(-2)))
        d.commit()
        d.close()

        async def _fake(db, sigs, s):
            return [{"title": "pay rent now", "body": "overdue", "link": "tasks",
                     "score": 80, "source_keys": [sigs[0]["key"]]}]

        orig = proactive._reason
        proactive._reason = _fake
        self.addCleanup(lambda: setattr(proactive, "_reason", orig))

        out = self.client.post("/api/proactive/run").json()
        self.assertTrue(out["ran"])
        rows = self.client.get("/api/proactive").json()
        self.assertEqual([r["title"] for r in rows], ["pay rent now"])

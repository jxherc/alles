from tests._client import ApiTest
from core.database import (Session, Message, Task, CalendarEvent, Contact,
                          Account, Transaction, Subscription)


class SearchApiTest(ApiTest):
    def test_empty_query_returns_empty_shape(self):
        r = self.client.get("/api/search", params={"q": ""}).json()
        self.assertEqual(set(r), {"chats", "notes", "tasks", "calendar", "contacts",
                                  "memories", "mail", "money", "subs", "photos"})
        self.assertTrue(all(r[k] == [] for k in r))

    def test_finds_money_and_subs(self):
        d = self.db()
        acct = Account(name="checking", opening=0.0); d.add(acct); d.commit()
        d.add(Transaction(account_id=acct.id, date="2026-06-01", amount=-9.99,
                          payee="zptest grocer", category="food"))
        d.add(Subscription(name="zptest plus", price=5, currency="$", cycle="monthly",
                          next_due="2026-07-01", category="apps"))
        d.commit(); d.close()
        r = self.client.get("/api/search", params={"q": "zptest"}).json()
        self.assertEqual([t["payee"] for t in r["money"]], ["zptest grocer"])
        self.assertEqual([s["name"] for s in r["subs"]], ["zptest plus"])

    def test_finds_across_surfaces(self):
        d = self.db()
        s = Session(name="a normal chat"); d.add(s); d.commit()
        d.add(Message(session_id=s.id, role="user", content="please remember zptest for later"))
        d.add(Task(title="zptest task"))
        d.add(CalendarEvent(title="zptest meeting", start_dt="2099-01-01T10:00:00"))
        d.add(Contact(name="Zptest Person", email="z@x.com", tags="[]"))
        d.commit(); d.close()
        # a memory too (keyword fallback works without fastembed)
        self.client.post("/api/memories", json={"text": "zptest is a thing I track"})

        r = self.client.get("/api/search", params={"q": "zptest"}).json()
        self.assertTrue(any("zptest" in c["snippet"].lower() for c in r["chats"]), r["chats"])
        self.assertEqual([t["title"] for t in r["tasks"]], ["zptest task"])
        self.assertEqual([e["title"] for e in r["calendar"]], ["zptest meeting"])
        self.assertEqual([c["name"] for c in r["contacts"]], ["Zptest Person"])
        self.assertTrue(any("zptest" in m["text"].lower() for m in r["memories"]), r["memories"])

    def test_no_cross_contamination(self):
        d = self.db(); d.add(Task(title="totally unrelated")); d.commit(); d.close()
        r = self.client.get("/api/search", params={"q": "zptest"}).json()
        self.assertEqual(r["tasks"], [])

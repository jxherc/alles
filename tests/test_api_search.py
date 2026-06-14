from tests._client import ApiTest
from core.database import Session, Message, Task, CalendarEvent, Contact


class SearchApiTest(ApiTest):
    def test_empty_query_returns_empty_shape(self):
        r = self.client.get("/api/search", params={"q": ""}).json()
        self.assertEqual(set(r), {"chats", "notes", "tasks", "calendar", "contacts", "memories"})
        self.assertTrue(all(r[k] == [] for k in r))

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

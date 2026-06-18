from datetime import datetime, timedelta

from tests._client import ApiTest
from core.database import Session, Message


class SessionsApiTest(ApiTest):
    def test_list_empty_shape(self):
        r = self.client.get("/api/sessions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"today": [], "yesterday": [], "earlier": []})

    def test_create_then_listed_today(self):
        r = self.client.post("/api/sessions", json={"name": "hello chat"})
        self.assertEqual(r.status_code, 200)
        sid = r.json()["id"]
        self.assertEqual(r.json()["name"], "hello chat")

        lst = self.client.get("/api/sessions").json()
        self.assertEqual([s["id"] for s in lst["today"]], [sid])

    def test_create_with_persona_and_project(self):
        r = self.client.post(
            "/api/sessions", json={"name": "p", "persona_id": "persona-1", "project_id": "proj-1"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["persona_id"], "persona-1")
        self.assertEqual(r.json()["project_id"], "proj-1")

    def test_incognito_hidden_from_list(self):
        self.client.post("/api/sessions", json={"name": "secret", "incognito": True})
        lst = self.client.get("/api/sessions").json()
        self.assertEqual(lst["today"], [])  # incognito leaves no trace in the sidebar

    def test_history_404_and_ok(self):
        self.assertEqual(self.client.get("/api/sessions/nope/history").status_code, 404)
        sid = self.client.post("/api/sessions", json={"name": "h"}).json()["id"]
        d = self.db()
        d.add(Message(session_id=sid, role="user", content="hi there"))
        d.commit()
        d.close()
        h = self.client.get(f"/api/sessions/{sid}/history").json()
        self.assertEqual(h["session"]["id"], sid)
        self.assertEqual([m["content"] for m in h["messages"]], ["hi there"])

    def test_patch_rename(self):
        sid = self.client.post("/api/sessions", json={"name": "old"}).json()["id"]
        r = self.client.patch(f"/api/sessions/{sid}", json={"name": "new name", "starred": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "new name")
        self.assertTrue(r.json()["starred"])

    def test_delete_blocked_when_starred(self):
        sid = self.client.post("/api/sessions", json={"name": "keep"}).json()["id"]
        self.client.patch(f"/api/sessions/{sid}", json={"starred": True})
        r = self.client.delete(f"/api/sessions/{sid}")
        self.assertEqual(r.status_code, 400)  # must unstar first
        self.client.patch(f"/api/sessions/{sid}", json={"starred": False})
        self.assertEqual(self.client.delete(f"/api/sessions/{sid}").status_code, 200)

    def test_archive_moves_out_of_list_into_archived(self):
        sid = self.client.post("/api/sessions", json={"name": "arch"}).json()["id"]
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/archive").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/sessions").json()["today"], [])
        archived = self.client.get("/api/sessions/archived").json()
        self.assertEqual([s["id"] for s in archived], [sid])

    def test_edit_message_truncates_later(self):
        sid = self.client.post("/api/sessions", json={"name": "edit"}).json()["id"]
        d = self.db()
        base = datetime.utcnow()
        m1 = Message(session_id=sid, role="user", content="first", timestamp=base)
        m2 = Message(
            session_id=sid, role="assistant", content="reply", timestamp=base + timedelta(seconds=1)
        )
        d.add_all([m1, m2])
        d.commit()
        mid = m1.id
        d.close()
        r = self.client.post(f"/api/sessions/{sid}/messages/{mid}/edit", json={"content": "edited"})
        self.assertEqual(r.status_code, 200)
        msgs = self.client.get(f"/api/sessions/{sid}/history").json()["messages"]
        self.assertEqual([m["content"] for m in msgs], ["edited"])  # the later reply was dropped

    def test_auto_name_heuristic_without_endpoint(self):
        sid = self.client.post("/api/sessions", json={"name": "new chat"}).json()["id"]
        # no messages yet → 400
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/auto-name").status_code, 400)
        d = self.db()
        d.add(Message(session_id=sid, role="user", content="How do I bake sourdough bread at home"))
        d.commit()
        d.close()
        # no enabled endpoint → heuristic strips the "how do i" lead-in, lowercases
        name = self.client.post(f"/api/sessions/{sid}/auto-name").json()["name"]
        self.assertTrue(name.startswith("bake sourdough"))
        self.assertEqual(name, name.lower())

import json
from datetime import datetime, timedelta
from unittest import mock

from tests._client import ApiTest
from core.database import Session, Message, ModelEndpoint


class SessionsApiTest(ApiTest):
    def test_edit_deletes_same_timestamp_reply(self):
        # a coarse clock can stamp the user msg and its assistant reply identically; editing the
        # user msg must still drop the stale reply (and everything after), not leave it dangling
        d = self.db()
        s = Session(name="c")
        d.add(s)
        d.flush()
        ts = datetime(2026, 6, 1, 12, 0, 0)
        u = Message(session_id=s.id, role="user", content="q", timestamp=ts)
        a = Message(session_id=s.id, role="assistant", content="old answer", timestamp=ts)
        d.add_all([u, a])
        d.commit()
        sid, uid, aid = s.id, u.id, a.id
        d.close()

        r = self.client.post(f"/api/sessions/{sid}/messages/{uid}/edit", json={"content": "q2"})
        self.assertEqual(r.status_code, 200)

        d = self.db()
        self.assertEqual(d.get(Message, uid).content, "q2")
        self.assertIsNone(d.get(Message, aid))  # stale same-timestamp reply removed
        d.close()

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

    def test_export_formats(self):
        sid = self.client.post("/api/sessions", json={"name": "My Chat"}).json()["id"]
        d = self.db()
        d.add(Message(session_id=sid, role="user", content="hi <b>there</b>"))
        d.add(Message(session_id=sid, role="assistant", content="hello back"))
        d.commit()
        d.close()

        # markdown (default)
        md = self.client.get(f"/api/sessions/{sid}/export")
        self.assertEqual(md.status_code, 200)
        self.assertIn("# My Chat", md.text)
        self.assertIn('filename="my-chat.md"', md.headers["content-disposition"])

        # json — structured, parseable
        import json as _j

        data = _j.loads(self.client.get(f"/api/sessions/{sid}/export?fmt=json").text)
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])

        # html — escapes content (no raw tag injection)
        h = self.client.get(f"/api/sessions/{sid}/export?fmt=html")
        self.assertIn("text/html", h.headers["content-type"])
        self.assertIn("&lt;b&gt;there&lt;/b&gt;", h.text)
        self.assertNotIn("<b>there</b>", h.text)

        # txt
        t = self.client.get(f"/api/sessions/{sid}/export?fmt=txt")
        self.assertIn("USER:", t.text)

    def test_export_bad_format_400_and_missing_404(self):
        sid = self.client.post("/api/sessions", json={"name": "x"}).json()["id"]
        self.assertEqual(self.client.get(f"/api/sessions/{sid}/export?fmt=pdf").status_code, 400)
        self.assertEqual(self.client.get("/api/sessions/nope/export").status_code, 404)

    def _seed_chat_with_reply(self):
        d = self.db()
        ep = ModelEndpoint(name="e", base_url="http://x", api_key="k",
                           cached_models=json.dumps(["m1"]))
        d.add(ep)
        d.flush()
        s = Session(name="c", model="m1", endpoint_id=ep.id)
        d.add(s)
        d.flush()
        d.add(Message(session_id=s.id, role="user", content="explain quantum tunneling"))
        am = Message(session_id=s.id, role="assistant", content="a very long winded answer " * 20)
        d.add(am)
        d.commit()
        sid, mid = s.id, am.id
        d.close()
        return sid, mid

    def test_rewrite_replaces_assistant_content(self):
        sid, mid = self._seed_chat_with_reply()

        async def _fake(messages, base, key, model, max_tokens=256):
            return "short version."

        with mock.patch("routes.chat.simple_complete", _fake):
            r = self.client.post("/api/chat/rewrite",
                                 json={"session_id": sid, "style": "shorter", "msg_id": mid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["content"], "short version.")
        # persisted
        h = self.client.get(f"/api/sessions/{sid}/history").json()
        last = [m for m in h["messages"] if m["role"] == "assistant"][-1]
        self.assertEqual(last["content"], "short version.")

    def test_rewrite_bad_style_400(self):
        sid, mid = self._seed_chat_with_reply()
        r = self.client.post("/api/chat/rewrite",
                             json={"session_id": sid, "style": "spicy", "msg_id": mid})
        self.assertEqual(r.status_code, 400)

    def test_rewrite_missing_message_404(self):
        sid, _ = self._seed_chat_with_reply()
        r = self.client.post("/api/chat/rewrite",
                             json={"session_id": sid, "style": "shorter", "msg_id": "nope"})
        self.assertEqual(r.status_code, 404)

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

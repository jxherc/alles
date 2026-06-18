from tests._client import ApiTest
from core.database import Session, Message


class SharedApiTest(ApiTest):
    def _seed_session(self, name="chat"):
        d = self.db()
        s = Session(name=name, model="aide")
        d.add(s)
        d.commit()
        d.add(Message(session_id=s.id, role="user", content="hello shared"))
        d.commit()
        sid = s.id
        d.close()
        return sid

    def test_share_idempotent_and_public_view(self):
        sid = self._seed_session()
        r = self.client.post(f"/api/sessions/{sid}/share").json()
        tok = r["token"]
        self.assertEqual(r["url"], f"/s/{tok}")
        # asking again returns the SAME token (no churn)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/share").json()["token"], tok)
        # public read-only page renders the conversation
        page = self.client.get(f"/s/{tok}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("hello shared", page.text)

    def test_revoke_kills_link(self):
        sid = self._seed_session()
        tok = self.client.post(f"/api/sessions/{sid}/share").json()["token"]
        self.assertEqual(self.client.delete(f"/api/sessions/{sid}/share").json(), {"ok": True})
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_share_missing_session_404(self):
        self.assertEqual(self.client.post("/api/sessions/nope/share").status_code, 404)

    def test_view_bad_token_404(self):
        self.assertEqual(self.client.get("/s/badtoken").status_code, 404)

from tests._client import ApiTest
from core.database import Session, Message, Share


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

    def test_revoke_nonexistent_session_404(self):
        self.assertEqual(self.client.delete("/api/sessions/nope/share").status_code, 404)

    def test_shared_page_shows_session_name(self):
        sid = self._seed_session("My Distinct Chat Title")
        tok = self.client.post(f"/api/sessions/{sid}/share").json()["token"]
        page = self.client.get(f"/s/{tok}")
        self.assertIn("My Distinct Chat Title", page.text)

    def test_generic_share_create_and_lookup(self):
        # seed a Share row directly (kind=session, ref = a fake id)
        d = self.db()
        sid = self._seed_session("generic")
        d.close()
        # mint via the generic /api/share endpoint
        r = self.client.post("/api/share", json={"kind": "session", "ref": sid})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("token", body)
        self.assertEqual(body["kind"], "session")
        # GET /api/share must return the same token
        r2 = self.client.get("/api/share", params={"kind": "session", "ref": sid})
        self.assertEqual(r2.json()["token"], body["token"])

    def test_generic_share_revoke(self):
        sid = self._seed_session("rev")
        self.client.post("/api/share", json={"kind": "session", "ref": sid})
        r = self.client.request(
            "DELETE", "/api/share", json={"kind": "session", "ref": sid}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        # token should now be gone
        r2 = self.client.get("/api/share", params={"kind": "session", "ref": sid})
        self.assertIsNone(r2.json()["token"])

    def test_session_share_url_format(self):
        sid = self._seed_session("url-test")
        r = self.client.post(f"/api/sessions/{sid}/share").json()
        tok = r["token"]
        # url must be /s/<token>
        self.assertEqual(r["url"], f"/s/{tok}")
        # token itself should be a non-empty hex-ish string
        self.assertTrue(len(tok) >= 16)

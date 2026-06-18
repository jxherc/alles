from tests._client import ApiTest


class MailDraftTests(ApiTest):
    def _make(self, **kw):
        body = {"account_id": "acct1", "to": "a@x.com", "subject": "hi", "body": "draft body"}
        body.update(kw)
        return self.client.post("/api/mail/drafts", json=body)

    def test_create_returns_id(self):
        r = self._make()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("id"))

    def test_list_contains_created(self):
        did = self._make(subject="findme").json()["id"]
        rows = self.client.get("/api/mail/drafts").json()
        self.assertIn(did, [d["id"] for d in rows])
        self.assertIn("findme", [d["subject"] for d in rows])

    def test_get_by_id(self):
        did = self._make(subject="one").json()["id"]
        d = self.client.get(f"/api/mail/drafts/{did}").json()
        self.assertEqual(d["subject"], "one")
        self.assertEqual(d["to"], "a@x.com")

    def test_update_keeps_id_changes_field(self):
        did = self._make(subject="old").json()["id"]
        r = self.client.post(
            "/api/mail/drafts", json={"id": did, "account_id": "acct1", "subject": "new"}
        )
        self.assertEqual(r.json()["id"], did)
        self.assertEqual(self.client.get(f"/api/mail/drafts/{did}").json()["subject"], "new")

    def test_update_does_not_create_duplicate(self):
        did = self._make().json()["id"]
        self.client.post(
            "/api/mail/drafts", json={"id": did, "account_id": "acct1", "subject": "edited"}
        )
        self.assertEqual(len(self.client.get("/api/mail/drafts").json()), 1)

    def test_delete(self):
        did = self._make().json()["id"]
        self.assertEqual(self.client.delete(f"/api/mail/drafts/{did}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/mail/drafts/{did}").status_code, 404)

    def test_get_unknown_404(self):
        self.assertEqual(self.client.get("/api/mail/drafts/nope").status_code, 404)

    def test_account_scope(self):
        self._make(account_id="A", subject="forA")
        self._make(account_id="B", subject="forB")
        rows = self.client.get("/api/mail/drafts", params={"account_id": "A"}).json()
        self.assertEqual([d["subject"] for d in rows], ["forA"])

    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/mail/drafts").json(), [])

    def test_newest_first(self):
        first = self._make(subject="first").json()["id"]
        second = self._make(subject="second").json()["id"]
        ids = [d["id"] for d in self.client.get("/api/mail/drafts").json()]
        self.assertEqual(ids[0], second)
        self.assertIn(first, ids)

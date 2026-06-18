from tests._client import ApiTest


class DocumentsApiTest(ApiTest):
    def test_crud(self):
        d = self.client.post("/api/documents", json={"title": "doc", "content": "hello"}).json()
        self.assertEqual(d["title"], "doc")
        self.assertEqual(d["content"], "hello")
        self.assertEqual(d["content_len"], 5)
        did = d["id"]

        self.assertEqual(self.client.get(f"/api/documents/{did}").json()["content"], "hello")
        r = self.client.patch(
            f"/api/documents/{did}", json={"content": "longer text", "title": "t2"}
        )
        self.assertEqual(r.json()["title"], "t2")
        self.assertEqual(r.json()["content"], "longer text")

        self.assertEqual([x["id"] for x in self.client.get("/api/documents").json()], [did])
        self.assertEqual(self.client.delete(f"/api/documents/{did}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/documents").json(), [])

    def test_missing_404(self):
        self.assertEqual(self.client.get("/api/documents/nope").status_code, 404)
        self.assertEqual(
            self.client.patch("/api/documents/nope", json={"title": "x"}).status_code, 404
        )
        self.assertEqual(self.client.delete("/api/documents/nope").status_code, 404)

    def test_ai_edit_without_endpoint_400(self):
        did = self.client.post("/api/documents", json={"title": "d", "content": "c"}).json()["id"]
        r = self.client.post(
            f"/api/documents/{did}/ai-edit", json={"instruction": "make it better"}
        )
        self.assertEqual(r.status_code, 400)  # no endpoint configured

    def test_ai_edit_missing_doc_404(self):
        self.assertEqual(
            self.client.post("/api/documents/nope/ai-edit", json={"instruction": "x"}).status_code,
            404,
        )

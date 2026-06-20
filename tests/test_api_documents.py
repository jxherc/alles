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

    def test_defaults(self):
        d = self.client.post("/api/documents", json={}).json()
        self.assertEqual(d["title"], "untitled")
        self.assertEqual(d["doc_type"], "md")
        self.assertEqual(d["content"], "")
        self.assertEqual(d["content_len"], 0)

    def test_list_no_content_field(self):
        self.client.post("/api/documents", json={"title": "x", "content": "abc"})
        lst = self.client.get("/api/documents").json()
        self.assertEqual(len(lst), 1)
        self.assertNotIn("content", lst[0])
        self.assertIn("content_len", lst[0])

    def test_ordering_newest_first(self):
        a = self.client.post("/api/documents", json={"title": "a"}).json()["id"]
        b = self.client.post("/api/documents", json={"title": "b"}).json()["id"]
        # touch a so it becomes most recently updated
        self.client.patch(f"/api/documents/{a}", json={"title": "a2"})
        ids = [x["id"] for x in self.client.get("/api/documents").json()]
        self.assertEqual(ids[0], a)
        self.assertEqual(ids[1], b)

    def test_patch_only_content_keeps_title(self):
        did = self.client.post(
            "/api/documents", json={"title": "keep-me", "content": "old"}
        ).json()["id"]
        r = self.client.patch(f"/api/documents/{did}", json={"content": "new"}).json()
        self.assertEqual(r["title"], "keep-me")
        self.assertEqual(r["content"], "new")

    def test_patch_only_title_keeps_content(self):
        did = self.client.post("/api/documents", json={"title": "t", "content": "stay"}).json()[
            "id"
        ]
        r = self.client.patch(f"/api/documents/{did}", json={"title": "renamed"}).json()
        self.assertEqual(r["title"], "renamed")
        self.assertEqual(r["content"], "stay")

    def test_patch_doc_type(self):
        did = self.client.post("/api/documents", json={"title": "t", "doc_type": "md"}).json()["id"]
        r = self.client.patch(f"/api/documents/{did}", json={"doc_type": "txt"}).json()
        self.assertEqual(r["doc_type"], "txt")

    def test_content_len_updates_after_patch(self):
        did = self.client.post("/api/documents", json={"content": "hi"}).json()["id"]
        self.assertEqual(self.client.get(f"/api/documents/{did}").json()["content_len"], 2)
        self.client.patch(f"/api/documents/{did}", json={"content": "longer now"})
        self.assertEqual(self.client.get(f"/api/documents/{did}").json()["content_len"], 10)

    def test_multiple_docs_in_list(self):
        ids = set()
        for i in range(3):
            ids.add(self.client.post("/api/documents", json={"title": f"d{i}"}).json()["id"])
        lst = self.client.get("/api/documents").json()
        self.assertEqual(len(lst), 3)
        self.assertEqual({x["id"] for x in lst}, ids)

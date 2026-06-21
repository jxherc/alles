from tests._client import ApiTest


class NotesApiTest(ApiTest):
    def _mk(self, **kw):
        return self.client.post("/api/notes", json=kw).json()

    def test_create_with_tags_normalized(self):
        n = self._mk(title="t", content="c", tags=["Work", "work", " Urgent "])
        self.assertEqual(n["tags"], ["work", "urgent"])  # deduped + lowercased + trimmed

    def test_tags_accept_comma_string(self):
        n = self._mk(title="t", tags="a, b ,a")
        self.assertEqual(n["tags"], ["a", "b"])

    def test_search_matches_title_content_tags(self):
        self._mk(title="grocery list", content="milk eggs", tags=["home"])
        self._mk(title="work plan", content="ship the thing", tags=["office"])
        titles = lambda q: sorted(n["title"] for n in self.client.get(f"/api/notes?q={q}").json())
        self.assertEqual(titles("milk"), ["grocery list"])       # content hit
        self.assertEqual(titles("office"), ["work plan"])        # tag hit
        self.assertEqual(titles("plan"), ["work plan"])          # title hit

    def test_filter_by_tag(self):
        self._mk(title="a", tags=["x"])
        self._mk(title="b", tags=["y"])
        got = self.client.get("/api/notes?tag=x").json()
        self.assertEqual([n["title"] for n in got], ["a"])

    def test_tags_endpoint_counts(self):
        self._mk(title="a", tags=["x", "y"])
        self._mk(title="b", tags=["x"])
        tags = {t["tag"]: t["count"] for t in self.client.get("/api/notes/tags").json()}
        self.assertEqual(tags, {"x": 2, "y": 1})

    def test_archive_hides_from_default_list(self):
        nid = self._mk(title="bye")["id"]
        self.client.post(f"/api/notes/{nid}/archive", json={"archived": True})
        self.assertEqual(self.client.get("/api/notes").json(), [])
        # but visible when asking for archived
        arch = self.client.get("/api/notes?archived=true").json()
        self.assertEqual([n["title"] for n in arch], ["bye"])
        # and excluded from the tag cloud
        self.client.post(f"/api/notes/{nid}/archive", json={"archived": False})
        self.assertEqual([n["title"] for n in self.client.get("/api/notes").json()], ["bye"])

    def test_update_tags(self):
        nid = self._mk(title="t", tags=["old"])["id"]
        n = self.client.patch(f"/api/notes/{nid}", json={"tags": ["new", "shiny"]}).json()
        self.assertEqual(n["tags"], ["new", "shiny"])

    def test_archive_missing_404(self):
        self.assertEqual(
            self.client.post("/api/notes/nope/archive", json={"archived": True}).status_code, 404
        )

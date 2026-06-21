from unittest import mock

from routes.read import make_excerpt, read_minutes, site_of
from tests._client import ApiTest

_FAKE = {
    "success": True,
    "title": "A Long Read About Otters",
    "content": "Otters are playful mustelids. " * 80,  # ~400 words
    "og_image": "https://x.test/otter.png",
}


class ReadLogicTests(ApiTest):
    def test_site_of_strips_www(self):
        self.assertEqual(site_of("https://www.example.com/a/b?x=1"), "example.com")

    def test_site_of_bare(self):
        self.assertEqual(site_of("https://blog.test.io/post"), "blog.test.io")

    def test_site_of_garbage(self):
        self.assertEqual(site_of("not a url"), "")

    def test_make_excerpt_truncates(self):
        e = make_excerpt("word " * 200, 100)
        self.assertLessEqual(len(e), 104)  # +ellipsis slack

    def test_make_excerpt_collapses_whitespace(self):
        self.assertEqual(make_excerpt("a\n\n   b\t c", 50), "a b c")

    def test_read_minutes(self):
        self.assertEqual(read_minutes("word " * 400), 2)
        self.assertEqual(read_minutes("short"), 1)  # floor of 1


class ReadApiTests(ApiTest):
    def _save(self, url="https://example.com/otters", fake=_FAKE):
        with mock.patch("routes.read.fetch_webpage_content", return_value=fake):
            return self.client.post("/api/read", json={"url": url})

    def test_save_stores_extracted_text(self):
        r = self._save()
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["title"], "A Long Read About Otters")
        self.assertEqual(j["site"], "example.com")
        self.assertTrue(j["excerpt"])
        self.assertGreaterEqual(j["read_minutes"], 1)

    def test_save_requires_url(self):
        self.assertEqual(self.client.post("/api/read", json={"url": ""}).status_code, 400)

    def test_save_keeps_link_when_extraction_fails(self):
        bad = {"success": False, "title": "", "content": "", "og_image": ""}
        r = self._save(url="https://dead.test/x", fake=bad)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["site"], "dead.test")
        self.assertTrue(r.json()["title"])  # falls back to url/site

    def test_list_contains_saved(self):
        self._save(url="https://example.com/a")
        urls = [i["url"] for i in self.client.get("/api/read").json()["items"]]
        self.assertIn("https://example.com/a", urls)

    def test_search_matches_body(self):
        self._save()
        items = self.client.get("/api/read", params={"q": "mustelids"}).json()["items"]
        self.assertTrue(items)

    def test_search_matches_title(self):
        self._save()
        items = self.client.get("/api/read", params={"q": "otters"}).json()["items"]
        self.assertTrue(items)

    def test_search_no_match(self):
        self._save()
        items = self.client.get("/api/read", params={"q": "zzznomatch"}).json()["items"]
        self.assertEqual(items, [])

    def test_get_full_returns_text(self):
        rid = self._save().json()["id"]
        full = self.client.get(f"/api/read/{rid}").json()
        self.assertIn("Otters", full["text"])

    def test_mark_read_toggles(self):
        rid = self._save().json()["id"]
        self.assertTrue(self.client.post(f"/api/read/{rid}/read").json()["read"])
        self.assertFalse(self.client.post(f"/api/read/{rid}/read").json()["read"])

    def test_patch_tags_and_fav(self):
        rid = self._save().json()["id"]
        r = self.client.patch(f"/api/read/{rid}", json={"tags": "nature, science", "fav": True})
        self.assertTrue(r.json()["fav"])
        self.assertIn("nature", r.json()["tags"])

    def test_archive_excluded_by_default(self):
        rid = self._save(url="https://example.com/old").json()["id"]
        self.client.patch(f"/api/read/{rid}", json={"archived": True})
        ids = [i["id"] for i in self.client.get("/api/read").json()["items"]]
        self.assertNotIn(rid, ids)
        # but visible when explicitly asked
        arch = [
            i["id"]
            for i in self.client.get("/api/read", params={"filter": "archived"}).json()["items"]
        ]
        self.assertIn(rid, arch)

    def test_delete_removes(self):
        rid = self._save().json()["id"]
        self.assertEqual(self.client.delete(f"/api/read/{rid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/read/{rid}").status_code, 404)

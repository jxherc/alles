import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from services import vault_md
from tests._client import ApiTest


class DocsPreviewTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_preview_found(self):
        vault_md.write("hello.md", "# Hello\n\nthis is the body text")
        d = self.client.get("/api/vault-md/preview", params={"name": "hello"}).json()
        self.assertTrue(d["found"])
        self.assertIn("body text", d["excerpt"])

    def test_preview_strips_frontmatter(self):
        vault_md.write("fm.md", "---\ntitle: X\n---\nactual content here")
        d = self.client.get("/api/vault-md/preview", params={"name": "fm"}).json()
        self.assertNotIn("title:", d["excerpt"])
        self.assertIn("actual content", d["excerpt"])

    def test_preview_unknown_not_found(self):
        d = self.client.get("/api/vault-md/preview", params={"name": "ghostzzz"}).json()
        self.assertFalse(d["found"])

    def test_preview_empty_name(self):
        d = self.client.get("/api/vault-md/preview", params={"name": ""}).json()
        self.assertFalse(d["found"])


class DocsBookmarkTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.sf.write(b"{}")
        self.sf.close()
        self._p = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self.sf.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        Path(self.sf.name).unlink(missing_ok=True)
        super().tearDown()

    def test_bookmark_toggle_on(self):
        r = self.client.post("/api/vault-md/bookmarks", json={"path": "a.md", "title": "A"}).json()
        self.assertTrue(r["bookmarked"])
        self.assertTrue(any(b["path"] == "a.md" for b in r["bookmarks"]))

    def test_bookmark_toggle_off(self):
        self.client.post("/api/vault-md/bookmarks", json={"path": "a.md", "title": "A"})
        r = self.client.post("/api/vault-md/bookmarks", json={"path": "a.md", "title": "A"}).json()
        self.assertFalse(r["bookmarked"])
        self.assertFalse(any(b["path"] == "a.md" for b in r["bookmarks"]))

    def test_bookmark_get_list(self):
        self.client.post("/api/vault-md/bookmarks", json={"path": "a.md", "title": "A"})
        self.client.post("/api/vault-md/bookmarks", json={"path": "b.md", "title": "B"})
        bms = self.client.get("/api/vault-md/bookmarks").json()["bookmarks"]
        self.assertEqual({b["path"] for b in bms}, {"a.md", "b.md"})

    def test_bookmark_persists(self):
        self.client.post("/api/vault-md/bookmarks", json={"path": "a.md", "title": "A"})
        bms = self.client.get("/api/vault-md/bookmarks").json()["bookmarks"]
        self.assertEqual(len(bms), 1)

    def test_bookmark_title_defaults_to_path(self):
        r = self.client.post("/api/vault-md/bookmarks", json={"path": "notitle.md"}).json()
        b = next(b for b in r["bookmarks"] if b["path"] == "notitle.md")
        self.assertEqual(b["title"], "notitle.md")

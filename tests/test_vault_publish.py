import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class PublishFolderTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        vault_md.write("pubs/a.md", "alpha — see [[b]] and [[ghost]]")
        vault_md.write("pubs/b.md", "beta content")
        vault_md.write("other/c.md", "gamma content")
        vault_md.write("_templates/t.md", "template")

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _publish(self, folder):
        return self.client.post("/api/vault-md/publish-folder", json={"folder": folder}).json()

    def test_publish_folder_mints_all(self):
        d = self._publish("pubs")
        self.assertEqual({p["path"] for p in d["published"]}, {"pubs/a.md", "pubs/b.md"})

    def test_publish_excludes_other_folders(self):
        d = self._publish("pubs")
        self.assertFalse(any("other/" in p["path"] for p in d["published"]))

    def test_publish_skips_hidden(self):
        d = self._publish("")  # root publish shouldn't grab _templates either
        self.assertFalse(any("_templates" in p["path"] for p in d["published"]))

    def test_published_doc_renders(self):
        d = self._publish("pubs")
        tok = next(p["token"] for p in d["published"] if p["path"] == "pubs/b.md")
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("beta content", r.text)

    def test_wikilink_links_to_published(self):
        d = self._publish("pubs")
        a_tok = next(p["token"] for p in d["published"] if p["path"] == "pubs/a.md")
        b_tok = next(p["token"] for p in d["published"] if p["path"] == "pubs/b.md")
        html = self.client.get(f"/s/{a_tok}").text
        self.assertIn(f'href="/s/{b_tok}"', html)

    def test_wikilink_unpublished_is_plain(self):
        d = self._publish("pubs")
        a_tok = next(p["token"] for p in d["published"] if p["path"] == "pubs/a.md")
        html = self.client.get(f"/s/{a_tok}").text
        self.assertIn("ghost", html)
        self.assertNotIn(">ghost</a>", html.replace("ghost", "ghost"))  # ghost is not a link
        # ensure no /s/ link wraps "ghost"
        self.assertNotRegex(html, r'href="/s/[^"]+">ghost')

    def test_publish_idempotent(self):
        d1 = self._publish("pubs")
        d2 = self._publish("pubs")
        t1 = {p["path"]: p["token"] for p in d1["published"]}
        t2 = {p["path"]: p["token"] for p in d2["published"]}
        self.assertEqual(t1, t2)

    def test_publish_count(self):
        d = self._publish("pubs")
        self.assertEqual(d["count"], 2)

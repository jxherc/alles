import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class FindBlockTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_inline_marker(self):
        vault_md.write("src.md", "first line\nthe shared block ^abc\nlast line")
        d = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "abc"}).json()
        self.assertTrue(d["found"])
        self.assertEqual(d["text"], "the shared block")

    def test_marker_with_caret_in_id_param(self):
        vault_md.write("src.md", "content here ^xyz")
        d = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "^xyz"}).json()
        self.assertEqual(d["text"], "content here")

    def test_marker_on_own_line_takes_paragraph(self):
        vault_md.write("src.md", "para line one\npara line two\n^blk\n\nother")
        d = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "blk"}).json()
        self.assertTrue(d["found"])
        self.assertEqual(d["text"], "para line one\npara line two")

    def test_unknown_block(self):
        vault_md.write("src.md", "nothing here")
        d = self.client.get(
            "/api/vault-md/block", params={"path": "src.md", "id": "missing"}
        ).json()
        self.assertFalse(d["found"])

    def test_unknown_note(self):
        d = self.client.get("/api/vault-md/block", params={"path": "ghost.md", "id": "x"}).json()
        self.assertFalse(d["found"])

    def test_picks_correct_id(self):
        vault_md.write("src.md", "alpha block ^a\nbeta block ^b")
        a = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "a"}).json()
        b = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "b"}).json()
        self.assertEqual(a["text"], "alpha block")
        self.assertEqual(b["text"], "beta block")

    def test_id_with_hyphen(self):
        vault_md.write("src.md", "hyphen block ^my-id")
        d = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "my-id"}).json()
        self.assertEqual(d["text"], "hyphen block")

    def test_no_false_match_substring(self):
        vault_md.write("src.md", "block one ^abcd")
        d = self.client.get("/api/vault-md/block", params={"path": "src.md", "id": "abc"}).json()
        self.assertFalse(d["found"])

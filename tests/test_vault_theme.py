import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class ThemeCssTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_default_empty(self):
        self.assertEqual(self.client.get("/api/vault-md/theme-css").json()["css"], "")

    def test_put_get_roundtrip(self):
        css = ".cm-content { font-family: Georgia }"
        self.client.put("/api/vault-md/theme-css", json={"css": css})
        self.assertEqual(self.client.get("/api/vault-md/theme-css").json()["css"], css)

    def test_writes_hidden_file(self):
        self.client.put("/api/vault-md/theme-css", json={"css": "x{}"})
        self.assertTrue((Path(self.tmp.name) / "_vault-theme.css").exists())

    def test_overwrite(self):
        self.client.put("/api/vault-md/theme-css", json={"css": "a{}"})
        self.client.put("/api/vault-md/theme-css", json={"css": "b{}"})
        self.assertEqual(self.client.get("/api/vault-md/theme-css").json()["css"], "b{}")

    def test_clear(self):
        self.client.put("/api/vault-md/theme-css", json={"css": "a{}"})
        self.client.put("/api/vault-md/theme-css", json={"css": ""})
        self.assertEqual(self.client.get("/api/vault-md/theme-css").json()["css"], "")

    def test_theme_not_in_tree(self):
        self.client.put("/api/vault-md/theme-css", json={"css": "a{}"})
        tree = self.client.get("/api/vault-md/tree").json()

        def names(items):
            out = []
            for it in items:
                out.append(it.get("name", ""))
                out += names(it.get("items", []) or it.get("children", []))
            return out

        self.assertFalse(any("_vault-theme" in n for n in names(tree.get("items", []))))

    def test_put_returns_ok(self):
        r = self.client.put("/api/vault-md/theme-css", json={"css": "body{}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_file_content_matches(self):
        css = "h1 { color: red; }\n/* comment */\n"
        self.client.put("/api/vault-md/theme-css", json={"css": css})
        disk = (Path(self.tmp.name) / "_vault-theme.css").read_text("utf-8")
        self.assertEqual(disk, css)

    def test_unicode_css_roundtrip(self):
        # emoji + cjk in css comments — encoding must survive the write/read cycle
        css = "/* éàü \U0001f525 中文 */ body{}"
        self.client.put("/api/vault-md/theme-css", json={"css": css})
        got = self.client.get("/api/vault-md/theme-css").json()["css"]
        self.assertEqual(got, css)

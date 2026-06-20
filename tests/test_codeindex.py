import asyncio
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from services import codeindex, textindex
from tests._client import ApiTest


def _mkrepo():
    d = tempfile.mkdtemp(prefix="codeidx-")
    Path(d, "auth.py").write_text(
        "def login(user, password):\n    # authenticate the user\n    return verify(user, password)\n"
    )
    Path(d, "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    Path(d, "logo.png").write_bytes(b"\x89PNG\r\n")
    (Path(d) / "node_modules").mkdir()
    Path(d, "node_modules", "junk.js").write_text("module.exports = 1\n")
    (Path(d) / ".git").mkdir()
    Path(d, ".git", "config.py").write_text("should be skipped\n")
    Path(d, "big.py").write_text("x = 1\n" * 100000)  # > 256 KB
    return d


class CodeIndexTests(ApiTest):
    def test_exts_filter(self):
        d = _mkrepo()
        names = {p.name for p in codeindex.iter_code_files(d)}
        self.assertIn("auth.py", names)
        self.assertNotIn("logo.png", names)

    def test_iter_skips_vcs_and_deps(self):
        d = _mkrepo()
        names = {p.name for p in codeindex.iter_code_files(d)}
        self.assertNotIn("junk.js", names)
        self.assertNotIn("config.py", names)

    def test_iter_skips_large(self):
        d = _mkrepo()
        names = {p.name for p in codeindex.iter_code_files(d)}
        self.assertNotIn("big.py", names)

    def test_reindex_counts(self):
        d = _mkrepo()
        db = self.db()
        n = codeindex.reindex(db, d)
        self.assertGreater(n, 0)
        self.assertGreater(codeindex.stats(db), 0)
        db.close()

    def test_search_finds_by_meaning(self):
        d = _mkrepo()
        db = self.db()
        codeindex.reindex(db, d)
        hits = codeindex.search(db, "login password authentication")
        db.close()
        self.assertTrue(hits)
        self.assertEqual(hits[0]["ref"], "auth.py")

    def test_search_scoped_to_code_kind(self):
        d = _mkrepo()
        db = self.db()
        codeindex.reindex(db, d)
        textindex.index(db, "doc", "notes.md", "login and password notes for the doc kind")
        hits = codeindex.search(db, "login password")
        db.close()
        self.assertTrue(hits)
        self.assertTrue(all(h["kind"] == "code" for h in hits))

    def test_search_empty_index(self):
        db = self.db()
        self.assertEqual(codeindex.search(db, "anything"), [])
        db.close()

    def test_stats_after_reindex(self):
        d = _mkrepo()
        db = self.db()
        n = codeindex.reindex(db, d)
        self.assertEqual(codeindex.stats(db), n)
        db.close()

    def test_api_search_shape(self):
        d = _mkrepo()
        db = self.db()
        codeindex.reindex(db, d)
        db.close()
        r = self.client.get("/api/code/search", params={"q": "login"}).json()
        self.assertIn("hits", r)
        self.assertTrue(any(h["ref"] == "auth.py" for h in r["hits"]))

    def test_api_reindex(self):
        d = _mkrepo()
        sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        sf.close()
        with mock.patch.object(core.settings, "_SETTINGS_FILE", Path(sf.name)):
            core.settings.save_settings({"agent_cwd": d})
            r = self.client.post("/api/code/reindex").json()
        Path(sf.name).unlink(missing_ok=True)
        self.assertGreater(r["indexed"], 0)

    def test_tool_search_code_returns_hits(self):
        import services.agent_tools as at

        d = _mkrepo()
        db = self.db()
        codeindex.reindex(db, d)
        db.close()
        res = asyncio.run(at.execute("search_code", {"query": "login authentication"}))
        self.assertTrue(res.get("hits"))
        self.assertTrue(any(h["ref"] == "auth.py" for h in res["hits"]))

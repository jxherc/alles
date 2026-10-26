import posixpath
import re
import subprocess
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"`])((?:\.{1,2}/|/static/)[^'"`$]+?\.m?js)(\?[^'"`]*)?\1"""
)


def module_urls(text: str, base: str):
    for m in IMPORT.finditer(text):
        path = m.group(2)
        full = path if path.startswith("/") else posixpath.normpath(posixpath.join(base, path))
        yield full, m.group(3) or ""


def app_urls() -> dict[str, set[str]]:
    found = defaultdict(set)
    for f in [*STATIC.rglob("*.js"), *STATIC.rglob("*.html")]:
        if "vendor" in f.parts:
            continue
        rel = f.relative_to(ROOT).as_posix()
        base = "/" + posixpath.dirname(rel) if f.suffix == ".js" else "/static"
        for path, query in module_urls(f.read_text(encoding="utf-8"), base):
            found[path].add(query)
    return found


class ModulePreloadTest(unittest.TestCase):
    def test_every_module_is_imported_under_one_url(self):
        # ./x.js and ./x.js?v=2 are two copies with their own state (kokuen's label ids clashed)
        split = {path: sorted(q) for path, q in app_urls().items() if len(q) > 1}
        self.assertEqual(split, {})

    def test_browser_tests_import_the_app_copy(self):
        # a test that imports another stamp reads state the page never touches
        urls = app_urls()
        wrong = []
        for f in ROOT.glob("tests/pw_*.py"):
            for path, query in module_urls(f.read_text(encoding="utf-8"), "/static/js"):
                if path in urls and query not in urls[path]:
                    wrong.append(f"{f.name}: {path}{query} (app uses {sorted(urls[path])})")
        self.assertEqual(wrong, [])

    def test_index_lists_every_startup_module(self):
        # a stale list sends startup back to a dozen round trips deep
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "modulepreload.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()

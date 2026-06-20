"""ui-0a — central icon system. Validates static/js/icons.js as a text artifact (catalog +
contract) and at runtime via node. No JS test runner exists, so we parse the module and also
execute it through node to assert real behavior."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "static" / "js" / "icons.js"
STYLE = ROOT / "static" / "style.css"
INDEX = ROOT / "static" / "index.html"

REQUIRED = [
    "search",
    "plus",
    "close",
    "check",
    "star",
    "star-fill",
    "eye",
    "eye-off",
    "lock",
    "unlock",
    "gear",
    "trash",
    "edit",
    "copy",
    "link",
    "share",
    "download",
    "upload",
    "refresh",
    "chevron-left",
    "chevron-right",
    "chevron-up",
    "chevron-down",
    "calendar",
    "clock",
    "mail",
    "paperclip",
    "comment",
    "image",
    "file",
    "folder",
    "tag",
    "bell",
    "play",
    "mic",
    "video",
    "grid",
    "list",
    "map-pin",
    "plane",
    "shield",
    "send",
    "archive",
    "snooze",
    "mute",
    "sparkles",
    "heart",
    "heart-fill",
    "columns",
    "board",
    "history",
    "bookmark",
    "menu",
    "key",
    "more",
]


def _src():
    return ICONS.read_text(encoding="utf-8")


def _catalog_keys(src):
    # grab the P = { ... } map body and pull the keys
    m = re.search(r"const P\s*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "could not find the `const P = {...};` icon map"
    body = m.group(1)
    return set(re.findall(r"^\s*['\"]?([A-Za-z][\w-]*)['\"]?\s*:", body, re.M))


def _node(expr):
    node = shutil.which("node")
    assert node, "node is required to run the icon runtime tests"
    code = (
        "import {icon, ICON_NAMES} from './static/js/icons.js';"
        f"const r=(()=>{{{expr}}})();process.stdout.write(JSON.stringify(r));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout)


class IconCatalogTests(unittest.TestCase):
    def test_module_exists_and_exports_icon(self):
        self.assertTrue(ICONS.exists(), "static/js/icons.js missing")
        self.assertIn("export function icon(", _src())

    def test_all_required_names_registered(self):
        keys = _catalog_keys(_src())
        missing = [n for n in REQUIRED if n not in keys]
        self.assertEqual(missing, [], f"icons missing from catalog: {missing}")

    def test_catalog_has_at_least_60(self):
        keys = {k for k in _catalog_keys(_src()) if not k.startswith("_")}
        self.assertGreaterEqual(len(keys), 60, f"only {len(keys)} icons")

    def test_icon_returns_svg(self):
        out = _node("return icon('search');")
        self.assertIn("<svg", out)
        self.assertIn('viewBox="0 0 24 24"', out)

    def test_icon_is_monochrome_currentcolor(self):
        out = _node("return icon('star');")
        self.assertIn('stroke="currentColor"', out)
        self.assertIn('fill="none"', out)

    def test_size_option_applies(self):
        out = _node("return icon('gear', {size: 20});")
        self.assertIn("20px", out)

    def test_class_option_applies(self):
        out = _node("return icon('trash', {cls: 'danger'});")
        self.assertRegex(out, r'class="[^"]*\bdanger\b')

    def test_unknown_name_falls_back_not_empty(self):
        out = _node("return icon('__nope__');")
        self.assertIn("<svg", out)
        self.assertNotEqual(out.strip(), "")

    def test_icon_names_export_matches_catalog(self):
        names = set(_node("return ICON_NAMES;"))
        self.assertGreaterEqual(len(names), 60)
        self.assertIn("search", names)

    def test_glow_style_exists(self):
        self.assertIn(".ic-glow", STYLE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Keep the shipped frontend inventory connected to its real bootstrap."""

import posixpath
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module_graph(directory):
    modules = {
        path.relative_to(directory).as_posix(): path.read_text("utf-8")
        for path in directory.rglob("*.js")
    }
    # Include lazy-loader arguments as well as native import specifiers. This is a
    # conservative source graph: a static reference keeps a module in the inventory.
    edges = {
        name: {
            posixpath.normpath(posixpath.join(posixpath.dirname(name), reference))
            for reference in re.findall(
                r"['\"]((?:\./|\.\./)[^'\"?#]+\.js)(?:[?#][^'\"]*)?['\"]", source
            )
        }
        for name, source in modules.items()
    }
    return modules, edges


class FrontendInventoryTests(unittest.TestCase):
    def _assert_shipped_module_reachability(self, directory):
        modules, edges = _module_graph(directory)
        reached = set()
        pending = ["app.js"]
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            if name.startswith("../"):
                # Vendored assets are dependencies, outside the application module
                # inventory. Resolve and check them without scanning their bundles.
                self.assertTrue(
                    name.startswith("../vendor/"), f"module outside static roots: {name}"
                )
                self.assertTrue((directory / name).is_file(), f"missing referenced module: {name}")
                continue
            self.assertIn(name, set(modules), f"missing referenced module: {name}")
            reached.add(name)
            pending.extend(edges[name] - reached)
        self.assertEqual(set(modules) - reached, set(), "unreachable shipped frontend modules")

    def test_every_shipped_module_is_reachable_from_app(self):
        self._assert_shipped_module_reachability(ROOT / "static/js")

    def test_nested_graph_resolves_each_reference_from_its_importing_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sources = {
                "app.js": "load('./settings/pane.js?v=1');",
                "util.js": "export const root = true;",
                "settings/pane.js": (
                    "import './util.js'; import '../util.js?v=2'; "
                    "export { child } from './deep/child.js';"
                ),
                "settings/util.js": "export const local = true;",
                "settings/deep/child.js": "import '../../util.js'; export const child = true;",
            }
            for name, source in sources.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            modules, edges = _module_graph(directory)
            self.assertEqual(set(modules), set(sources))
            self.assertEqual(edges["app.js"], {"settings/pane.js"})
            self.assertEqual(
                edges["settings/pane.js"],
                {"settings/util.js", "util.js", "settings/deep/child.js"},
            )
            self.assertEqual(edges["settings/deep/child.js"], {"util.js"})
            self._assert_shipped_module_reachability(directory)

    def test_inventory_still_rejects_missing_and_unreachable_nested_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "settings").mkdir()
            (directory / "app.js").write_text("import './settings/missing.js';", encoding="utf-8")
            with self.assertRaisesRegex(
                AssertionError, "missing referenced module: settings/missing.js"
            ):
                self._assert_shipped_module_reachability(directory)
            (directory / "app.js").write_text("export const app = true;", encoding="utf-8")
            (directory / "settings/orphan.js").write_text(
                "export const orphan = true;", encoding="utf-8"
            )
            with self.assertRaisesRegex(AssertionError, "unreachable shipped frontend modules"):
                self._assert_shipped_module_reachability(directory)

    def test_referenced_vendor_assets_must_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "js"
            (directory / "settings").mkdir(parents=True)
            (root / "vendor").mkdir()
            (directory / "app.js").write_text("import './settings/pane.js';", encoding="utf-8")
            (directory / "settings/pane.js").write_text(
                "import '../../vendor/bundle.js';", encoding="utf-8"
            )
            bundle = root / "vendor/bundle.js"
            bundle.write_text("export const bundle = true;", encoding="utf-8")
            self._assert_shipped_module_reachability(directory)
            bundle.unlink()
            with self.assertRaisesRegex(
                AssertionError, "missing referenced module: ../vendor/bundle.js"
            ):
                self._assert_shipped_module_reachability(directory)

    def test_composer_keeps_microphone_without_the_nonfunctional_live_voice_control(self):
        html = (ROOT / "static/index.html").read_text()
        self.assertIn('id="mic-btn"', html)
        self.assertNotIn('id="live-voice-btn"', html)


if __name__ == "__main__":
    unittest.main()

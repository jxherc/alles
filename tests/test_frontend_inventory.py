"""Keep the shipped frontend inventory connected to its real bootstrap."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontendInventoryTests(unittest.TestCase):
    def test_every_shipped_module_is_reachable_from_app(self):
        modules = {path.name: path.read_text() for path in (ROOT / "static/js").glob("*.js")}
        # Include lazy-loader arguments as well as native import specifiers. This is a
        # conservative source graph: a static reference keeps a module in the inventory.
        edges = {
            name: set(re.findall(r"['\"]\./([^'\"?]+\.js)(?:\?[^'\"]*)?['\"]", source))
            for name, source in modules.items()
        }
        reached = set()
        pending = ["app.js"]
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            self.assertIn(name, modules, f"missing referenced module: {name}")
            reached.add(name)
            pending.extend(edges[name] - reached)
        self.assertEqual(set(modules) - reached, set(), "unreachable shipped frontend modules")

    def test_composer_keeps_microphone_without_the_nonfunctional_live_voice_control(self):
        html = (ROOT / "static/index.html").read_text()
        self.assertIn('id="mic-btn"', html)
        self.assertNotIn('id="live-voice-btn"', html)


if __name__ == "__main__":
    unittest.main()

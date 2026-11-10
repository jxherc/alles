import unittest
from pathlib import Path

from scripts import settings_homes


class SettingsHomesTest(unittest.TestCase):
    def test_every_setting_has_one_home_in_every_layout(self):
        self.assertEqual(settings_homes.check(table=False), [])

    def test_a_lost_pane_fails_the_check(self):
        layouts = settings_homes.organizations()
        layouts["jobs"][0]["panes"].remove("general")
        original = settings_homes.organizations
        settings_homes.organizations = lambda: layouts
        try:
            self.assertIn("jobs: general has 0 homes", settings_homes.check(table=False))
        finally:
            settings_homes.organizations = original

    def test_the_picked_layout_groups_models_with_how_aide_answers(self):
        jobs = {g["group"]: g["panes"] for g in settings_homes.organizations()["jobs"]}
        self.assertIn("models", jobs["settings.org_how_aide_answers"])
        self.assertIn("personas", jobs["settings.org_how_aide_answers"])
        self.assertIn("search", jobs["settings.org_what_aide_knows"])
        self.assertIn("@server", jobs["settings.org_safety"])

    def test_the_ledger_setup_has_a_stable_home_in_settings(self):
        # u.05: the finance overview links to it with openSettingsAt("s-ledger")
        # or /?view=settings#s-ledger, so the anchor must stay inside a settings pane
        root = Path(__file__).resolve().parents[1]
        html = (root / "static" / "index.html").read_text()
        machine = html.index('id="s-pane-machine"')
        anchor = html.index('id="s-ledger"')
        self.assertLess(machine, anchor)
        self.assertLess(anchor, html.index('id="s-pane-developer"'))
        self.assertIn('id="s-ledger-body"', html)
        app = (root / "static" / "js" / "app.js").read_text()
        self.assertIn("openSettingsAt(decodeURIComponent(location.hash.slice(1)))", app)
        settings = (root / "static" / "js" / "settings.js").read_text()
        self.assertIn("export function openSettingsAt(id)", settings)


if __name__ == "__main__":
    unittest.main()

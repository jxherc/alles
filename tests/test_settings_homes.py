import unittest

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


if __name__ == "__main__":
    unittest.main()

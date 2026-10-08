"""One Home source contract; browser gates cover rendered behavior."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class ShellIdentityTests(unittest.TestCase):
    def test_app_identity_is_one_anchor_without_a_home_breadcrumb(self):
        self.assertIn("crumb-app", APP)
        self.assertNotIn("crumb-root", APP)
        self.assertNotIn("crumb-root", CSS)
        self.assertIn("urlForApp(appSub)", APP)
        self.assertNotIn("urlForApp('')", APP)

    def test_modified_clicks_allow_native_new_tab(self):
        self.assertRegex(APP, r"metaKey\s*\|\|\s*e\.ctrlKey\s*\|\|\s*e\.shiftKey")

    def test_hub_crumb_is_plain_wordmark(self):
        self.assertIn("if (appName === 'alles')", APP)

    def test_aide_brand_uses_one_local_identity_link(self):
        self.assertIn("_buildCrumb(brand, 'aide', 'aide')", APP)
        self.assertIn(".crumb-app {", CSS)

    def test_app_name_navigates_via_href_not_intercepted(self):
        self.assertIn("appA.href = urlForApp(appSub)", APP)
        self.assertNotIn("navigateTo(appForSub(s).primary)", APP)


class OneHomeTests(unittest.TestCase):
    def test_one_home_surface_owns_capture_day_and_apps(self):
        self.assertEqual(INDEX.count('id="today-view"'), 1)
        self.assertNotIn('id="home-view"', INDEX)
        for control in ("today-capture", "today-capture-input", "today-ask-aide", "today-sections"):
            with self.subTest(control=control):
                self.assertIn(f'id="{control}"', INDEX)
        self.assertIn('id="app-drawer"', INDEX)

    def test_duplicate_launcher_runtime_and_styles_are_gone(self):
        for dead in (
            "function renderHome(",
            "function _wireHomeAsk(",
            "function _renderHomeTiles(",
            "function _wireQuickCapture(",
            "function _renderToday(",
            "function _startHomeClock(",
        ):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, APP)
        self.assertNotIn(".home-tile", CSS)
        self.assertNotIn(".home-today", CSS)

    def test_legacy_preferences_remain_readable_for_one_time_import(self):
        self.assertIn("alles-home-order", APP)
        self.assertIn("alles-home-hidden", APP)
        self.assertIn("readLegacyHomeShortcuts", APP)
        self.assertIn("legacyShortcuts: readLegacyHomeShortcuts", APP)

    def test_first_run_wizard_still_opens_from_the_current_home(self):
        current_home = APP.split("const showTodayView", 1)[1].split("const showAndromedaView", 1)[0]
        self.assertIn("_renderFirstRun();", current_home)


if __name__ == "__main__":
    unittest.main()

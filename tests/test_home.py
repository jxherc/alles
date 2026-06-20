"""ui-1a..1e — home + global chrome contracts (source-level, deterministic). Runtime layout
(5 tiles/row, grid above ask, jiggle) is verified separately in the Playwright sweep."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class BreadcrumbTests(unittest.TestCase):
    def test_crumb_built_from_two_anchors(self):
        self.assertIn("crumb-app", APP)
        self.assertIn("crumb-root", APP)
        self.assertIn("urlForApp(appSub)", APP)
        self.assertIn("urlForApp('')", APP)

    def test_modified_clicks_allow_native_new_tab(self):
        # ctrl/cmd/shift click must NOT be hijacked (so middle/new-tab works)
        self.assertRegex(APP, r"metaKey\s*\|\|\s*e\.ctrlKey\s*\|\|\s*e\.shiftKey")

    def test_hub_crumb_is_plain_wordmark(self):
        self.assertIn("if (appName === 'alles')", APP)

    def test_brand_home_uses_split_crumb(self):
        self.assertIn("_buildCrumb(brand, 'aide', 'aide')", APP)
        self.assertIn(".crumb-app, .crumb-root", CSS)

    def test_app_name_navigates_via_href_not_intercepted(self):
        # clicking the app name (e.g. "docs") should follow its href to the app's own root
        # (= the app's home page) — the click handler only intercepts the "alles" root part.
        self.assertIn("appA.href = urlForApp(appSub)", APP)
        self.assertNotIn("navigateTo(appForSub(s).primary)", APP)


class HomeLayoutTests(unittest.TestCase):
    def test_grid_is_five_columns(self):
        m = re.search(r"\.home-grid\s*\{[^}]*grid-template-columns:\s*repeat\((\d+),", CSS)
        self.assertTrue(m)
        self.assertEqual(int(m.group(1)), 5)

    def test_home_inner_is_wider(self):
        m = re.search(r"\.home-inner\s*\{[^}]*max-width:\s*(\d+)px", CSS)
        self.assertTrue(m)
        self.assertGreaterEqual(int(m.group(1)), 1000)

    def test_home_order_schedule_capture_ask_grid(self):
        # order: schedule(+capture in the board) → quick message → everything else
        board = INDEX.index('class="home-board"')
        ask = INDEX.index('id="home-ask"')
        grid = INDEX.index('id="home-grid"')
        self.assertLess(board, ask, "board (schedule+capture) before quick message")
        self.assertLess(ask, grid, "quick message before the tile grid")

    def test_schedule_and_capture_share_one_box(self):
        # the schedule + note/task capture live inside one .home-board container
        board = INDEX.index('class="home-board"')
        nxt = INDEX.index("</div>", INDEX.index('id="home-capture"'))
        self.assertLess(board, INDEX.index('id="home-today"'))
        self.assertLess(INDEX.index('id="home-today"'), INDEX.index('id="home-capture"'))
        self.assertIn(".home-board", CSS)
        self.assertGreater(nxt, board)


class HomeTilesTests(unittest.TestCase):
    def test_aide_tile_present(self):
        # the aide card stays on the home grid (only the quick-message "aide ↗" button was removed)
        self.assertRegex(APP, r"view:\s*'chat',\s*name:\s*'aide'")

    def test_no_aide_goto_button_in_quick_message(self):
        self.assertNotIn('id="ha-goto"', INDEX)


class QuickMessageTests(unittest.TestCase):
    def test_input_is_quick_message(self):
        self.assertIn('placeholder="quick message…"', INDEX)
        self.assertNotIn("ask aide about your day…", INDEX)

    def test_about_my_day_off_quick_bar(self):
        # the redundant quick-message "about my day" button is removed; the day summary lives on the
        # dedicated day-section button (#ht-ask → _askAideAboutToday) instead
        self.assertNotIn('id="ha-day"', INDEX)
        self.assertIn('id="ht-ask"', APP)   # the day-section "ask aide about my day" button (rendered by app.js)

    def test_send_is_plain_day_is_contextual(self):
        self.assertIn("ask(false)", APP)  # plain send
        self.assertIn("ask(true)", APP)  # about-my-day button
        self.assertIn("if (withDay)", APP)


class JiggleTests(unittest.TestCase):
    def test_jiggle_keyframe_exists(self):
        self.assertIn("@keyframes home-jiggle", CSS)

    def test_editing_tiles_animate(self):
        self.assertRegex(
            CSS, r"\.home-grid\.editing\s+\.home-tile\s*\{[^}]*animation:\s*home-jiggle"
        )


if __name__ == "__main__":
    unittest.main()

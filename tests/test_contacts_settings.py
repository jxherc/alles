"""ui-7b (frontend contract) — CardDAV is off the toolbar and lives in the contacts settings cog.
Backend interval logic is covered by tests/test_carddav_interval.py."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "contacts.js").read_text(encoding="utf-8")
APPSET = (ROOT / "static" / "js" / "appsettings.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
EN = json.loads((ROOT / "static" / "locales" / "en.json").read_text(encoding="utf-8"))["messages"]


class CardDavInSettings(unittest.TestCase):
    def test_toolbar_button_removed(self):
        self.assertNotIn("contacts-carddav-btn", INDEX)
        self.assertNotIn("contacts-carddav-btn", JS)

    def test_contacts_cog_added(self):
        self.assertIn('class="icon-btn app-cog" data-app="contacts"', INDEX)

    def test_settings_spec_has_carddav_action(self):
        self.assertIn("contacts: {", APPSET)
        self.assertIn("act: '_contactsCardDav'", APPSET)

    def test_hook_exposed(self):
        self.assertIn("window._contactsCardDav = showCardDav", JS)

    def test_pane_has_interval_control(self):
        self.assertIn("cdav-interval", JS)
        self.assertIn("/api/carddav/interval", JS)
        # off/hourly/daily choices
        self.assertIn("['off', t('contacts.sync_manual')]", JS)
        self.assertIn("['hourly', t('contacts.sync_hourly')]", JS)
        self.assertIn("['daily', t('contacts.sync_daily')]", JS)
        self.assertEqual(
            [EN[f"contacts.sync_{k}"] for k in ("manual", "hourly", "daily")],
            ["manual", "hourly", "daily"],
        )

    def test_pane_glyphs_unified(self):
        # the old ✓ connected / ← contacts glyphs are gone from the pane
        self.assertNotIn("✓ connected", JS)
        self.assertIn("_si('check')", JS)
        self.assertRegex(CSS, r"\.carddav-status\.on")
        self.assertRegex(CSS, r"\.carddav-help")


if __name__ == "__main__":
    unittest.main()

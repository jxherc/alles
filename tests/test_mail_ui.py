"""Stage 4 (mail) UI contracts — source-level checks for the mail toolbar/chrome.
Behavioral flows live in docs/evidence/ui-4*/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MAIL = (ROOT / "static" / "js" / "mail.js").read_text(encoding="utf-8")
APPSET = (ROOT / "static" / "js" / "appsettings.js").read_text(encoding="utf-8")


class ToolbarCleanup4a(unittest.TestCase):
    def test_threads_button_removed(self):
        self.assertNotIn("mail-threads-btn", INDEX)
        self.assertNotIn("mail-threads-btn", MAIL)

    def test_search_is_live_not_enter_only(self):
        # the old keydown-Enter-only handler is gone; an input handler drives it
        self.assertRegex(MAIL, r"mail-search'\)\?\.addEventListener\('input'")
        self.assertNotIn("search mail… (enter)", INDEX)
        self.assertIn('placeholder="search mail…"', INDEX)

    def test_enter_still_works(self):
        self.assertRegex(MAIL, r"mail-search'\)\?\.addEventListener\('keydown'")

    def test_compose_is_rightmost(self):
        # compose is the last text button in the action group (before the cog), after refresh
        head = INDEX[INDEX.index("mail-head-actions"):]
        self.assertLess(head.index("mail-refresh-btn"), head.index("mail-compose-btn"))
        # nothing but the settings cog comes after compose
        after = head[head.index("mail-compose-btn"):]
        self.assertNotIn('class="btn"', after.split("app-cog")[0].replace("btn primary", ""))

    def test_grouping_moved_to_settings(self):
        # the threads toggle now lives in mail settings + is read from the setting
        self.assertIn("mail_threads", APPSET)
        self.assertIn("group by conversation", APPSET)
        self.assertIn("mail_threads === 'group'", MAIL)

    def test_reload_hook_for_settings(self):
        self.assertIn("window._reloadMail", MAIL)


CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class Sidebar4b(unittest.TestCase):
    def test_sidebar_replaces_horizontal_tabs(self):
        self.assertIn('id="mail-sidebar"', INDEX)
        self.assertIn("mail-layout", INDEX)
        # the old horizontal tab strip markup is gone from the head
        self.assertNotIn('class="mail-tabs"', INDEX)

    def test_nav_uses_unified_icons(self):
        self.assertIn("_MAIL_NAV", MAIL)
        self.assertIn("window.icon", MAIL)
        # all 9 categories present
        for f in ("inbox", "cat:primary", "cat:social", "cat:promotions", "unread", "flagged", "vip", "sent", "drafts"):
            self.assertIn(f"'{f}'", MAIL)

    def test_toggle_persists(self):
        self.assertIn("mail-sidebar-toggle", INDEX)
        self.assertIn("mail-sidebar-collapsed", MAIL)
        self.assertRegex(CSS, r"#mail-view\.sidebar-collapsed\s+\.mail-sidebar")

    def test_setfilter_targets_nav_items(self):
        self.assertIn(".mail-nav-item", MAIL)
        self.assertRegex(CSS, r"\.mail-nav-item\.active")


class SearchAndAccounts4c(unittest.TestCase):
    def test_search_centered_with_cap(self):
        self.assertRegex(CSS, r"\.mail-head\s+\.mail-search\s*\{[^}]*max-width:\s*560px")
        self.assertRegex(CSS, r"\.mail-head\s+\.mail-search\s*\{[^}]*margin:\s*0 auto")
        self.assertRegex(CSS, r"\.mail-head\s+\.mail-search\s*\{[^}]*flex:\s*1")

    def test_account_picker_pinned_left(self):
        self.assertRegex(CSS, r"\.mail-account-select\s*\{[^}]*flex-shrink:\s*0")

    def test_all_inboxes_option_for_multiple_accounts(self):
        self.assertIn("_accounts.length > 1", MAIL)
        self.assertIn("label: 'all inboxes'", MAIL)
        self.assertIn("value: 'all'", MAIL)


class Compose4d(unittest.TestCase):
    def test_chip_fields_replace_plain_inputs(self):
        self.assertIn("function _initChipField", MAIL)
        self.assertIn('class="mc-chipfield"', MAIL)
        # the old plain cc/bcc inputs are gone
        self.assertNotIn('id="mc-cc" placeholder="cc (optional)"', MAIL)
        self.assertRegex(CSS, r"\.mc-chip\b")

    def test_chips_mirror_to_hidden_inputs(self):
        # send/schedule/save still read $('mc-to').value — chips sync into a hidden input
        self.assertRegex(MAIL, r"hidden\.value = chips\.join")
        self.assertIn('<input type="hidden" id="mc-to">', MAIL)

    def test_cc_bcc_toggles(self):
        self.assertIn("mc-add-cc", MAIL)
        self.assertIn("mc-add-bcc", MAIL)

    def test_autocomplete_from_contacts_and_recipients(self):
        self.assertIn("function _loadAddrBook", MAIL)
        self.assertIn("/api/contacts", MAIL)
        self.assertIn("/api/mail/recipients", MAIL)
        self.assertRegex(CSS, r"\.mc-ac\b")

    def test_schedule_uses_a_date_picker(self):
        self.assertIn("initDatePicker as _dpInit", MAIL)
        self.assertIn("mc-sched-date", MAIL)
        self.assertIn("date-input", MAIL)
        # no more manual ISO text box
        self.assertNotIn("send at YYYY-MM-DDTHH:MM", MAIL)

    def test_bigger_compose_body(self):
        self.assertRegex(CSS, r"\.mail-compose-body\s*\{[^}]*min-height:\s*300px")


APPSET = (ROOT / "static" / "js" / "appsettings.js").read_text(encoding="utf-8")


class RulesAccountsInSettings4e(unittest.TestCase):
    def test_toolbar_buttons_removed(self):
        self.assertNotIn("mail-rules-btn", INDEX)
        self.assertNotIn("mail-accounts-btn", INDEX)
        self.assertNotIn("mail-rules-btn", MAIL)
        self.assertNotIn("mail-accounts-btn", MAIL)

    def test_settings_has_action_fields(self):
        self.assertIn("type: 'action'", APPSET)
        self.assertIn("act: '_mailAccounts'", APPSET)
        self.assertIn("act: '_mailRules'", APPSET)

    def test_action_field_type_supported(self):
        self.assertIn("f.type === 'action'", APPSET)
        self.assertIn("aps-action", APPSET)
        self.assertIn("window[btn.dataset.act]", APPSET)

    def test_hooks_exposed_by_mail(self):
        self.assertIn("window._mailAccounts", MAIL)
        self.assertIn("window._mailRules", MAIL)

    def test_action_styled(self):
        self.assertRegex(CSS, r"\.aps-action\b")


if __name__ == "__main__":
    unittest.main()

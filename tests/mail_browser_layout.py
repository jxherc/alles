"""Exercise concurrent mail panes through the supported responsive layout."""

from contextlib import contextmanager

from playwright.sync_api import expect


@contextmanager
def split_mail_panes(page):
    """Keep pane races covered by widening, then restore the original phone size.

    Compact Mail deliberately hides the list while an editor or reader is open.
    Tests requiring concurrent list/editor actions must use the split layout;
    restoring the phone viewport before delayed responses also covers resize races.
    """
    viewport = page.viewport_size
    compact = viewport["width"] <= 1100
    if compact:
        if page.locator(".mail-pane-back").count():
            expect(page.locator("#mail-list")).to_be_hidden()
        page.set_viewport_size({**viewport, "width": 1440})
        expect(page.locator("#mail-list")).to_be_visible()
    try:
        yield
    finally:
        if compact:
            page.set_viewport_size(viewport)
            if page.locator(".mail-pane-back").count():
                expect(page.locator("#mail-list")).to_be_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def return_to_mail_list(page):
    """Use the visible compact back path before choosing another message."""
    if page.viewport_size["width"] <= 1100:
        page.locator(".mail-pane-back").click()
        expect(page.locator("#mail-list")).to_be_visible()


def open_row_menu(page, row):
    """Open a message row's "more" menu from the keyboard, as its owner does."""
    # a menu closes on a window resize, and a resize after a layout change can land late: ask again
    for attempt in range(3):
        row.locator(".mail-more").focus()
        page.keyboard.press("Enter")
        try:
            expect(row.locator(".mail-menu")).to_be_visible(timeout=1500)
            return
        except AssertionError:
            if attempt == 2:
                raise


def row_action(page, row, action):
    """Open a row's menu and pick one action (label, mute, snooze, archive, unsubscribe).

    A menu closes on a resize or a repaint of the list, so a pick that finds it gone opens it again.
    """
    for attempt in range(3):
        open_row_menu(page, row)
        try:
            row.locator("[data-" + action + "]").click(timeout=2000)
            return
        except Exception:
            if attempt == 2:
                raise


def open_toolbar_menu(page):
    """Open the toolbar's "more" menu (refresh, mail settings)."""
    page.locator("#mail-more").click()
    expect(page.locator("#mail-more-menu")).to_be_visible()


def open_mail_settings(page):
    """Open mail settings from the toolbar's "more" menu."""
    open_toolbar_menu(page)
    page.locator("#mail-settings-btn").click()


def refresh_mail(page):
    open_toolbar_menu(page)
    page.locator("#mail-refresh-btn").click()


def choose_folder(page, folder):
    """Pick a folder in the toolbar dropdown by its filter value (unread, drafts, cat:primary)."""
    page.locator("#mail-folder").click()
    page.get_by_role("option", name=folder.removeprefix("cat:"), exact=True).click()

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

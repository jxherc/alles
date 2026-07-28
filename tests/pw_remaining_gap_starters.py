"""Rendered local-only checks for the Plan-board and scheduled-News starters."""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTERS = ROOT / "docs" / "mockups" / "afterlife-specialists"
EVIDENCE = Path(os.environ.get("ALLES_TEST_EVIDENCE", "/tmp/alles-remaining-gap-starters"))


def _visible(page, selector):
    return page.locator(selector).evaluate(
        "el => !el.hidden && getComputedStyle(el).display !== 'none' && !!el.getClientRects().length"
    )


def _no_page_overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _no_native_choices(page):
    forbidden = (
        "select, input[type=checkbox], input[type=radio], input[type=date], "
        "input[type=time], input[type=datetime-local]"
    )
    return page.locator(forbidden).count() == 0


def _theme_is(page, theme):
    return page.locator("html").get_attribute("data-theme") == theme


def _touch_targets_pass(page):
    undersized = page.locator("button:visible, a[href]:visible").evaluate_all(
        """elements => elements.map(element => {
            const box = element.getBoundingClientRect();
            return {
                label: element.getAttribute('aria-label') || element.textContent.trim(),
                width: box.width,
                height: box.height,
            };
        }).filter(item => item.width < 43.5 || item.height < 43.5)"""
    )
    if undersized:
        print("undersized_touch_targets:", undersized)
    return not undersized


def _open(page, filename):
    page.goto((STARTERS / filename).as_uri(), wait_until="domcontentloaded")
    page.wait_for_selector(".app-owned-header")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = {}
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            service_workers="block",
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )

        _open(page, "plan-kanban-v2.html")
        results["plan_no_native_choices"] = _no_native_choices(page)
        results["plan_identity_once"] = page.locator(".app-name", has_text="plan").count() == 1
        results["plan_four_active_columns"] = page.locator(".board-column").count() == 4
        results["plan_no_desktop_overflow"] = _no_page_overflow(page)
        page.screenshot(path=str(EVIDENCE / "plan-board-dark-desktop.png"), full_page=True)

        page.fill("#board-quick-title", "check Sunday weather")
        page.click("#board-quick-add")
        results["plan_quick_add"] = (
            page.locator('.board-card[data-title="check Sunday weather"]').count() == 1
        )
        page.click('.board-card[data-task-id="train"] .board-card-button')
        page.click("#task-move-forward")
        results["plan_keyboard_equivalent_move"] = (
            page.locator('.board-card[data-task-id="train"]').get_attribute("data-stage") == "next"
        )
        page.click("#board-filter-trigger")
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        results["plan_custom_filter_keyboard"] = (
            page.locator("#board-filter-trigger").inner_text() == "project: jxherc.com"
        )
        page.click("button[data-open-modal]")
        results["plan_completed_dialog"] = _visible(page, "#starter-modal")
        page.keyboard.press("Escape")

        page.set_viewport_size({"width": 390, "height": 844})
        _open(page, "plan-kanban-v2.html")
        page.locator('[data-mobile-stage-choice="doing"]').focus()
        page.keyboard.press("ArrowRight")
        results["plan_mobile_stage_keyboard"] = page.locator(
            '[data-mobile-stage-choice="waiting"]'
        ).get_attribute("aria-checked") == "true" and _visible(
            page, '.board-column[data-stage="waiting"]'
        )
        page.click('[data-mobile-stage-choice="doing"]')
        results["plan_no_mobile_overflow"] = _no_page_overflow(page)
        results["plan_phone_touch_targets"] = _touch_targets_pass(page)
        page.click('[data-switch="theme"]')
        results["plan_light_theme"] = _theme_is(page, "light")
        page.screenshot(path=str(EVIDENCE / "plan-board-light-phone.png"), full_page=True)

        page.set_viewport_size({"width": 640, "height": 800})
        results["plan_200_percent_reflow"] = _no_page_overflow(page)

        page.set_viewport_size({"width": 1280, "height": 800})
        _open(page, "news-workflow.html")
        results["news_no_native_choices"] = _no_native_choices(page)
        results["news_identity_once"] = page.locator(".app-name", has_text="aide").count() == 1
        results["news_default_off"] = (
            page.locator("#news-workflow-state").inner_text() == "news is off"
        )
        results["news_no_desktop_overflow"] = _no_page_overflow(page)
        page.screenshot(path=str(EVIDENCE / "news-dark-desktop.png"), full_page=True)

        page.click("#news-enable")
        results["news_enable_action"] = (
            page.locator("#news-workflow-state").get_attribute("data-enabled") == "true"
        )
        page.locator('[data-choice-group="schedule"][data-choice="morning"]').focus()
        page.keyboard.press("ArrowDown")
        results["news_choice_keyboard"] = (
            page.locator('[data-choice-group="schedule"][data-choice="evening"]').get_attribute(
                "aria-checked"
            )
            == "true"
        )
        page.click("button[data-open-modal]")
        page.click("#source-test")
        results["news_source_test_before_save"] = (
            _visible(page, "#source-test-result") and not page.locator("#source-save").is_disabled()
        )
        page.click("#source-save")
        results["news_source_dialog_focus_return"] = page.locator(
            "#starter-modal"
        ).is_hidden() and page.evaluate("document.activeElement?.hasAttribute('data-open-modal')")
        save = page.locator("[data-save-article]").first
        save.click()
        results["news_explicit_library_save"] = save.get_attribute("aria-pressed") == "true"

        page.set_viewport_size({"width": 390, "height": 844})
        _open(page, "news-workflow.html")
        results["news_no_mobile_overflow"] = _no_page_overflow(page)
        results["news_phone_touch_targets"] = _touch_targets_pass(page)
        page.click('[data-switch="theme"]')
        results["news_light_theme"] = _theme_is(page, "light")
        page.screenshot(path=str(EVIDENCE / "news-light-phone.png"), full_page=True)

        page.set_viewport_size({"width": 640, "height": 800})
        results["news_200_percent_reflow"] = _no_page_overflow(page)
        browser.close()

    results["zero_console_errors"] = not errors
    for name, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    if errors:
        print("console_errors:", errors[:8])
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

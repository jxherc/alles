from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8042/kokuen-universal-language.html"
SCREENSHOT_DIR = Path("/tmp/alles-kokuen-system")


def assert_no_page_overflow(page) -> None:
    overflow = page.evaluate(
        """() => ({
            viewport: document.documentElement.clientWidth,
            page: document.documentElement.scrollWidth,
            body: document.body.scrollWidth,
        })"""
    )
    assert overflow["page"] <= overflow["viewport"] + 1, overflow
    assert overflow["body"] <= overflow["viewport"] + 1, overflow


def check_desktop(browser) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL, wait_until="networkidle")

    assert page.locator("#current-app").inner_text() == "files"
    assert page.locator(".topbar").bounding_box()["height"] == 52
    assert page.locator(".topbar [data-theme-choice]").count() == 0
    assert page.locator("select").count() == 0
    assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0

    page.locator("#app-trigger").click()
    page.locator('[data-app="tasks"]').click()
    assert page.locator("#current-app").inner_text() == "tasks"
    task = page.locator(".task-row").first
    before = task.get_attribute("aria-pressed")
    task.click()
    assert task.get_attribute("aria-pressed") != before
    page.screenshot(path=str(SCREENSHOT_DIR / "tasks-desktop.png"), full_page=True)

    page.locator("#app-trigger").click()
    page.locator('[data-app="calendar"]').click()
    page.locator("#month-next").click()
    assert page.locator("#month-label").inner_text() == "august 2026"
    page.screenshot(path=str(SCREENSHOT_DIR / "calendar-desktop.png"), full_page=True)

    page.locator("#app-trigger").click()
    page.locator('[data-app="files"]').click()
    page.locator('.file-row[data-file="system-map.md"]').click()
    assert page.locator("#file-detail-title").inner_text() == "system-map.md"
    page.screenshot(path=str(SCREENSHOT_DIR / "files-desktop.png"), full_page=True)

    page.locator("#app-trigger").click()
    page.locator('[data-app="money"]').click()
    assert page.locator("#view-money").is_visible()
    page.screenshot(path=str(SCREENSHOT_DIR / "money-desktop.png"), full_page=True)

    page.locator("#settings-action").click()
    assert page.locator("#settings-panel").is_visible()
    assert page.locator(".shell").evaluate("element => element.inert")
    page.locator("#settings-close").focus()
    page.keyboard.press("Shift+Tab")
    assert page.locator('[data-state-choice="normal"]').evaluate(
        "element => element === document.activeElement"
    )
    page.keyboard.press("Tab")
    assert page.locator("#settings-close").evaluate("element => element === document.activeElement")
    page.locator('[data-theme-choice="dark"]').focus()
    page.keyboard.press("ArrowRight")
    assert page.locator('[data-theme-choice="light"]').get_attribute("aria-checked") == "true"
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.locator('[data-theme-choice="light"]').click()
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.locator('[data-density-choice="comfortable"]').click()
    assert page.locator("html").get_attribute("data-density") == "comfortable"
    page.locator('[data-state-choice="loading"]').click()
    assert page.locator("#state-layer").is_visible()
    assert page.locator("#settings-panel").is_hidden()
    page.locator("#settings-action").click()
    page.locator('[data-state-choice="partial"]').click()
    assert page.locator("#partial-line").is_visible()
    page.locator("#settings-action").click()
    page.locator('[data-state-choice="error"]').click()
    assert page.locator("#state-layer").is_visible()
    page.locator("#state-retry").click()
    assert page.locator("#state-layer").is_hidden()
    page.locator("#settings-action").click()
    page.locator('[data-theme-choice="dark"]').click()
    page.locator("#settings-close").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"

    page.locator("#app-trigger").focus()
    page.keyboard.press("Enter")
    assert page.locator("#app-menu").is_visible()
    page.keyboard.press("ArrowUp")
    assert page.locator('[data-app="files"]').evaluate(
        "element => element === document.activeElement"
    )
    page.keyboard.press("Escape")
    assert page.locator("#app-menu").is_hidden()
    page.locator("#app-trigger").click()
    page.locator('[data-app="tasks"]').click()
    assert page.locator("#app-trigger").evaluate("element => element === document.activeElement")

    assert_no_page_overflow(page)
    page.screenshot(path=str(SCREENSHOT_DIR / "desktop.png"), full_page=True)
    assert not errors, errors
    page.close()


def check_mobile(browser) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL, wait_until="networkidle")

    assert page.locator("#current-app").inner_text() == "files"
    assert page.locator(".detail-panel").is_hidden()
    page.locator("#app-trigger").click()
    page.locator('[data-app="tasks"]').click()
    assert page.locator("#view-tasks").is_visible()
    page.locator("#settings-action").click()
    assert page.locator("#settings-panel").bounding_box()["width"] <= 359
    page.keyboard.press("Escape")
    assert page.locator("#settings-panel").is_hidden()
    assert_no_page_overflow(page)
    page.screenshot(path=str(SCREENSHOT_DIR / "mobile.png"), full_page=True)
    assert not errors, errors
    page.close()


def check_reduced_motion(browser) -> None:
    page = browser.new_page(
        viewport={"width": 960, "height": 700},
        reduced_motion="reduce",
    )
    page.goto(BASE_URL, wait_until="networkidle")
    duration = page.locator("#app-trigger").evaluate(
        "element => getComputedStyle(element).transitionDuration"
    )
    assert duration in {"0s", "0ms"}, duration
    page.close()


def check_zoom_sized_viewport(browser) -> None:
    page = browser.new_page(viewport={"width": 720, "height": 450})
    page.goto(BASE_URL, wait_until="networkidle")
    page.locator("#settings-action").click()
    panel = page.locator("#settings-panel").bounding_box()
    assert panel["x"] >= 0
    assert panel["x"] + panel["width"] <= 721
    assert_no_page_overflow(page)
    page.close()


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        check_desktop(browser)
        check_mobile(browser)
        check_reduced_motion(browser)
        check_zoom_sized_viewport(browser)
        browser.close()
    print(
        "kokuen universal language starter passed desktop, mobile, keyboard, themes, states, 200% zoom sizing, overflow, and reduced-motion checks"
    )


if __name__ == "__main__":
    main()

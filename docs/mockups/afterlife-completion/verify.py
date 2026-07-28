from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


BASE = os.environ.get("STARTER_URL", "http://127.0.0.1:8988/index.html")
SHOT_DIR = Path(os.environ.get("STARTER_SHOTS", "/tmp/alles-completion-starter"))


def no_overflow(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def errors(page: Page, bucket: list[str]) -> None:
    page.on("pageerror", lambda error: bucket.append(f"page: {error}"))
    page.on("console", lambda message: bucket.append(f"console: {message.text}") if message.type == "error" else None)


def open_surface(page: Page, name: str) -> None:
    page.locator(f'[data-surface="{name}"]').click()
    page.locator(f"#surface-{name}").wait_for(state="visible")


def desktop(page: Page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.locator("#surface-files").wait_for()
    assert page.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
    assert page.locator('[data-surface="files"]').get_attribute("aria-selected") == "true"
    page.locator('[data-surface="files"]').focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement?.dataset?.surface") == "aide"
    page.keyboard.press("End")
    assert page.evaluate("document.activeElement?.dataset?.surface") == "server"
    page.keyboard.press("Home")
    assert page.evaluate("document.activeElement?.dataset?.surface") == "files"

    page.locator('[data-scope="connected"]').click()
    assert page.locator("#scope-title").inner_text() == "Connected"
    for state in ("loading", "offline", "error"):
        page.locator(f'[data-preview-state="{state}"]').click()
        assert page.locator("#files-state-message").is_visible()
    page.locator('[data-action="retry-files"]').click()
    assert page.locator("#file-list").is_visible()
    location_trigger = page.locator('[data-open-dialog="location-dialog"]')
    location_trigger.click()
    dialog = page.locator("#location-dialog")
    assert dialog.is_visible()
    first_choice = dialog.locator('[role="radio"]').first
    first_choice.focus()
    page.keyboard.press("ArrowDown")
    assert dialog.locator('[role="radio"]').nth(1).get_attribute("aria-checked") == "true"
    page.keyboard.press("Escape")
    assert dialog.is_hidden()
    assert page.evaluate("document.activeElement?.dataset?.openDialog") == "location-dialog"

    open_surface(page, "aide")
    first = page.locator('#question-form [role="radio"]').first
    first.focus()
    page.keyboard.press("ArrowDown")
    assert page.locator('#question-form [role="radio"]').nth(1).get_attribute("aria-checked") == "true"
    history = page.locator('#question-form [role="checkbox"][data-value="history"]')
    history.focus()
    page.keyboard.press("Space")
    assert history.get_attribute("aria-checked") == "true"
    page.locator('#question-form button[type="submit"]').click()
    assert "answers saved locally" in page.locator("#question-status").inner_text()

    open_surface(page, "providers")
    page.locator('[data-provider="OpenAI"]').click()
    assert page.locator("#provider-title").inner_text() == "connect OpenAI"
    page.locator("#provider-dialog input").fill("not-a-real-key")
    page.locator('#provider-dialog button[type="submit"]').click()
    assert page.locator("#provider-dialog").is_hidden()
    page.locator('[data-open-dialog="proxy-dialog"]').click()
    page.keyboard.press("Escape")

    open_surface(page, "finance")
    page.locator('[data-open-dialog="bank-dialog"]').click()
    submit = page.locator("[data-consent-submit]")
    assert submit.is_disabled()
    page.locator("[data-consent-check]").click()
    assert not submit.is_disabled()
    submit.click()
    assert page.locator("#bank-dialog").is_hidden()
    page.locator('[data-action="sync-bank"]').click()
    assert "0 new transactions" in page.locator("#global-status").inner_text()

    open_surface(page, "server")
    page.locator('[data-open-dialog="adguard-dialog"]').click()
    assert page.locator("#adguard-dialog button:has-text('activate DNS')").is_disabled()
    page.locator("#adguard-dialog [data-close-dialog]").first.click()
    page.locator('[data-open-dialog="npm-dialog"]').click()
    page.locator('[data-action="retry-docker"]').click()
    assert "Docker remains unavailable" in page.locator("#global-status").inner_text()
    page.keyboard.press("Escape")

    page.locator("#theme-toggle").click()
    assert page.locator("html").get_attribute("data-theme") == "light"
    no_overflow(page)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    for surface in ("files", "aide", "providers", "finance", "server"):
        open_surface(page, surface)
        no_overflow(page)
        page.screenshot(path=str(SHOT_DIR / f"desktop-light-{surface}.png"), full_page=True)


def responsive(page: Page, width: int, height: int, name: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE, wait_until="domcontentloaded")
    for surface in ("files", "aide", "providers", "finance", "server"):
        open_surface(page, surface)
        no_overflow(page)
        page.screenshot(path=str(SHOT_DIR / f"{name}-{surface}.png"), full_page=True)


def run() -> None:
    found: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 920}, reduced_motion="reduce", service_workers="block")
        page = context.new_page()
        page.set_default_timeout(10_000)
        errors(page, found)
        desktop(page)
        responsive(page, 720, 920, "desktop-200-percent")
        responsive(page, 390, 844, "phone")
        context.close()
        browser.close()
    if found:
        raise AssertionError("browser errors:\n" + "\n".join(found))
    print("completion starter browser gate passed")


if __name__ == "__main__":
    run()

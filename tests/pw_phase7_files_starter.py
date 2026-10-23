"""Browser gate for the standalone Phase 7 Files and storage starter."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "docs" / "mockups" / "afterlife-navigation" / "files-storage.html"


def _capture_errors(page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_context(
            viewport={"width": 1440, "height": 900}, reduced_motion="reduce"
        )
        page = desktop.new_page()
        _capture_errors(page, errors)
        page.goto(STARTER.as_uri(), wait_until="networkidle")

        assert page.locator(".location-button").count() == 3
        assert page.locator(".file-row").count() == 6
        assert page.locator(".preview-panel").is_visible()
        assert page.locator("select").count() == 0
        assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".file-name").first.evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize) >= 12"
        )
        assert page.locator(".preview-panel").evaluate(
            "el => parseFloat(getComputedStyle(el).transitionDuration) <= 0.001"
        )

        first_check = page.locator(".file-row .check").first
        first_check.focus()
        page.keyboard.press("Space")
        assert first_check.get_attribute("aria-checked") == "true"
        assert page.locator("#selection-count").inner_text() == "1 selected"
        page.locator(".file-row").nth(1).focus()
        page.keyboard.press("Space")
        assert page.locator("#selection-count").inner_text() == "2 selected"
        page.locator('[data-queue="copy"]').click()
        assert "copy queued" in page.locator("#operation-title").inner_text()
        assert page.locator("#operation-dock").is_visible()

        search = page.locator("#file-search")
        search.fill("budget")
        assert page.locator(".file-row:not([hidden])").count() == 1
        search.fill("")

        page.locator("#demo-button").click()
        assert page.locator("#demo-menu").is_visible()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        assert page.locator("#loading-state").is_visible()
        assert page.locator("#ready-state").is_hidden()

        page.locator("#demo-button").click()
        page.locator('[data-state="partial"]').click()
        assert page.locator("#partial-note").is_visible()
        assert "cached listing" in page.locator("#sync-state").inner_text()

        page.locator("#demo-button").click()
        page.locator('[data-state="empty"]').click()
        assert page.locator("#empty-state").is_visible()
        page.locator("#demo-button").click()
        page.locator('[data-state="error"]').click()
        assert page.locator("#error-state").is_visible()
        page.locator("#error-state [data-state-target]").click()
        assert page.locator("#ready-state").is_visible()

        page.locator(".location-button").nth(2).click()
        assert page.locator("#crumb-location").inner_text() == "archive S3"
        assert page.locator("#partial-note").is_visible()
        page.locator("#offline-button").click()
        assert page.locator("#offline-button").get_attribute("aria-pressed") == "false"
        assert page.locator("#offline-state").inner_text() == "online only"

        page.locator("#theme-button").click()
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert page.locator("body").evaluate(
            "el => getComputedStyle(el).backgroundColor === 'rgb(244, 243, 240)'"
        )
        page.screenshot(path="/tmp/alles-files-phase7-desktop.png", full_page=True)
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844}, reduced_motion="reduce"
        )
        page = mobile.new_page()
        _capture_errors(page, errors)
        page.goto(STARTER.as_uri(), wait_until="networkidle")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".location-panel").evaluate(
            "el => getComputedStyle(el).overflowX === 'auto'"
        )
        page.locator(".file-row").first.click()
        assert page.locator("#preview-panel").is_visible()
        page.locator("#preview-close").click()
        assert page.locator("#preview-panel").evaluate("el => el.classList.contains('closed')")
        page.locator(".file-row").nth(1).focus()
        page.keyboard.press("Space")
        assert page.locator("#selection-count").inner_text() == "1 selected"
        assert page.locator("#operation-dock").is_visible()
        page.screenshot(path="/tmp/alles-files-phase7-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("phase 7 Files starter browser gate passed")


if __name__ == "__main__":
    run()

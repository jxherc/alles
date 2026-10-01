"""Browser gate for the standalone Phase 6 Apps consistency starter."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "docs" / "mockups" / "afterlife-navigation" / "apps.html"


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_context(
            viewport={"width": 1440, "height": 980}, reduced_motion="reduce"
        )
        page = desktop.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.goto(STARTER.as_uri(), wait_until="networkidle")
        assert page.locator("h1").inner_text() == "apps"
        assert page.locator(".intro").count() == 0
        assert page.locator(".app-group").count() == 3
        assert page.locator("[data-app]").count() == 9
        assert page.locator("select").count() == 0
        assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".app-name").first.evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize) >= 15"
        )
        page.locator('[data-app="docs"]').focus()
        assert page.locator('[data-app="docs"]').evaluate(
            "el => getComputedStyle(el).outlineStyle !== 'none'"
        )
        page.keyboard.press("Enter")
        assert "docs would open here" in page.locator("#status").inner_text()
        page.screenshot(path="/tmp/alles-apps-phase6-desktop.png", full_page=True)
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844}, reduced_motion="reduce"
        )
        page = mobile.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.goto(STARTER.as_uri(), wait_until="networkidle")
        assert page.locator(".directory").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".app-button").first.evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        page.screenshot(path="/tmp/alles-apps-phase6-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("phase 6 Apps consistency starter browser gate passed")


if __name__ == "__main__":
    run()

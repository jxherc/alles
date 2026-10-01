"""Browser gate for the standalone Phase 6 Docs starter."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "docs" / "mockups" / "afterlife-navigation" / "docs.html"


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

        assert page.locator("#document-view").is_visible()
        assert page.locator("#visual-view").is_visible()
        assert page.locator("#source-view").is_hidden()
        assert page.locator("select").count() == 0
        assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator("#document-title").evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize) >= 32"
        )
        assert page.locator(".visual-view").evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize) >= 16"
        )
        assert page.locator(".loading-mark").evaluate(
            "el => getComputedStyle(el, '::after').animationName === 'none'"
        )
        page.screenshot(path="/tmp/alles-docs-starter-desktop.png", full_page=True)

        page.locator("#source-mode").click()
        assert page.locator("#source-view").is_visible()
        source = page.locator("#source-editor")
        source.evaluate("el => el.setSelectionRange(el.value.length, el.value.length)")
        source.type("\n<!-- local draft -->")
        assert "local draft" in page.locator("#save-state").inner_text()
        assert page.locator("#line-numbers").inner_text().splitlines()[-1] == str(
            len(source.input_value().split("\n"))
        )

        page.locator("#state-button").click()
        assert page.locator("#state-menu").is_visible()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        assert page.locator("#conflict-banner").is_visible()
        assert page.locator("#state-button").get_attribute("aria-expanded") == "false"

        page.locator("#state-button").click()
        page.locator('[data-state="empty"]').click()
        assert page.locator("#empty-state").is_visible()
        page.locator("#empty-state [data-return]").click()
        assert page.locator("#document-view").is_visible()

        page.locator("#state-button").click()
        page.locator('[data-state="error"]').click()
        assert page.locator("#error-state").is_visible()
        page.locator("#error-state [data-return]").click()

        search = page.locator("#doc-search")
        search.fill("meeting")
        assert page.locator("#document-list li:not([hidden])").count() == 1
        page.locator("#document-list li:not([hidden]) .document-choice").click()
        assert page.locator("#document-title").inner_text() == "meeting notes"
        page.screenshot(path="/tmp/alles-docs-starter-source-desktop.png", full_page=True)
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
        page.screenshot(path="/tmp/alles-docs-starter-mobile.png", full_page=True)
        assert page.locator("#docs-nav").evaluate("el => getComputedStyle(el).transform !== 'none'")
        page.locator("#mobile-nav").click()
        assert page.locator("#docs-nav").get_attribute("class") == "nav-panel open"
        assert page.locator("#scrim").is_visible()
        nav_box = page.locator("#docs-nav").bounding_box()
        assert nav_box and nav_box["width"] <= 390
        page.locator("#scrim").click(position={"x": 360, "y": 100})
        assert "open" not in (page.locator("#docs-nav").get_attribute("class") or "")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.locator("#source-mode").click()
        assert page.locator("#source-editor").is_visible()
        assert page.locator("select").count() == 0
        assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0
        page.screenshot(path="/tmp/alles-docs-starter-source-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("phase 6 Docs starter browser gate passed")


if __name__ == "__main__":
    run()

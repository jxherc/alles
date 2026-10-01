"""Browser gate for the standalone Home customization Settings starter."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "docs" / "mockups" / "afterlife-navigation" / "home-settings.html"


def _capture_errors(page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )


def _section_order(page) -> list[str]:
    return page.locator("#section-list > .outline-row").evaluate_all(
        "rows => rows.map(row => row.dataset.section)"
    )


def _contrast(page, foreground: str, background: str) -> float:
    return page.evaluate(
        """([foreground, background]) => {
          const rgb = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
          const luminance = value => rgb(value).map(channel => {
            const n = channel / 255;
            return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
          const a = luminance(foreground);
          const b = luminance(background);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        }""",
        [foreground, background],
    )


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_context(
            viewport={"width": 1440, "height": 980}, reduced_motion="reduce"
        )
        page = desktop.new_page()
        _capture_errors(page, errors)
        page.goto(STARTER.as_uri(), wait_until="networkidle")

        assert page.locator("#section-list > .outline-row").count() == 5
        assert page.locator("#shortcut-list > .outline-row").count() == 6
        assert page.locator("select").count() == 0
        assert page.locator('input[type="checkbox"], input[type="radio"]').count() == 0
        assert page.locator('[role="switch"]').count() == 11
        assert page.locator('[role="radiogroup"] [role="radio"]').count() == 2
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".save-button").evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        assert page.locator(".move").first.evaluate(
            "el => el.getBoundingClientRect().width >= 44 && el.getBoundingClientRect().height >= 44"
        )
        assert page.locator(".switch").first.evaluate(
            "el => el.getBoundingClientRect().width >= 44 && el.getBoundingClientRect().height >= 44"
        )
        assert page.locator(".switch").first.evaluate(
            "el => getComputedStyle(el, '::before').borderRadius === '99px'"
        )
        assert page.locator(".switch").first.evaluate(
            "el => getComputedStyle(el, '::after').borderRadius === '50%'"
        )
        assert page.locator('[data-section="needs_you"] [role="switch"]').is_disabled()
        assert (
            page.locator('[data-section="needs_you"] [role="switch"]').get_attribute("aria-checked")
            == "true"
        )
        skip_link = page.locator(".skip-link")
        skip_link.focus()
        assert skip_link.bounding_box()["y"] >= 0
        page.evaluate("document.activeElement?.blur()")
        assert page.locator(".outline-row").first.evaluate(
            "el => parseFloat(getComputedStyle(el).transitionDuration) <= 0.001"
        )

        page.locator('[data-section="needs_you"] [data-move="down"]').click()
        assert _section_order(page)[:2] == ["today", "needs_you"]
        assert (
            page.locator("#preview-list > :not([hidden])").first.get_attribute(
                "data-preview-section"
            )
            == "today"
        )

        briefs = page.locator('[data-section="briefs"] [role="switch"]')
        briefs.focus()
        page.keyboard.press("Space")
        assert briefs.get_attribute("aria-checked") == "false"
        assert page.locator('[data-preview-section="briefs"]').is_hidden()
        assert page.locator("#preview-count").inner_text() == "4 sections"

        comfortable = page.locator('[role="radio"][data-density="comfortable"]')
        comfortable.focus()
        page.keyboard.press("ArrowRight")
        assert (
            page.locator('[role="radio"][data-density="compact"]').get_attribute("aria-checked")
            == "true"
        )
        assert page.locator("#home-preview").get_attribute("data-density") == "compact"

        page.locator('[data-section="needs_you"] [data-move="down"]').click()
        assert page.locator('[data-section="needs_you"] [data-move="down"]').evaluate(
            "el => el === document.activeElement"
        )

        mail = page.locator('[data-shortcut="mail"] [role="switch"]')
        mail.click()
        assert "mail" in page.locator("#preview-shortcuts").inner_text()
        page.locator('[data-shortcut="mail"] [data-move="up"]').click()
        assert "unsaved" in page.locator("#save-state").inner_text()
        page.locator("#save-home").click()
        assert page.locator("#save-state").inner_text() == "saved just now · preview only"

        page.locator("#reset-home").click()
        assert _section_order(page) == ["needs_you", "today", "in_progress", "briefs", "shortcuts"]
        assert (
            page.locator('[role="radio"][data-density="comfortable"]').get_attribute("aria-checked")
            == "true"
        )
        assert (
            page.locator('[data-shortcut="mail"] [role="switch"]').get_attribute("aria-checked")
            == "false"
        )
        page.reload(wait_until="networkidle")
        page.evaluate("document.activeElement?.blur()")
        page.screenshot(path="/tmp/alles-home-settings-starter-desktop.png", full_page=True)

        body = page.locator("body")
        dark_foreground = body.evaluate("el => getComputedStyle(el).color")
        dark_background = body.evaluate("el => getComputedStyle(el).backgroundColor")
        assert _contrast(page, dark_foreground, dark_background) >= 7
        page.evaluate("document.documentElement.dataset.theme = 'light'")
        light_foreground = body.evaluate("el => getComputedStyle(el).color")
        light_background = body.evaluate("el => getComputedStyle(el).backgroundColor")
        assert light_background == "rgb(244, 243, 240)"
        assert _contrast(page, light_foreground, light_background) >= 7
        page.evaluate("document.documentElement.style.zoom = '2'")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
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
        assert page.locator(".settings-nav").evaluate(
            "el => getComputedStyle(el).overflowX === 'auto'"
        )
        assert page.locator(".home-workbench").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
        )
        page.locator('[data-section="today"] [role="switch"]').focus()
        page.keyboard.press("Space")
        assert page.locator('[data-preview-section="today"]').is_hidden()
        page.reload(wait_until="networkidle")
        page.evaluate("document.activeElement?.blur()")
        page.screenshot(path="/tmp/alles-home-settings-starter-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("Home customization Settings starter browser gate passed")


if __name__ == "__main__":
    run()

"""Rendered gate for the standalone Phase 10 localization and credits starter."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "docs" / "mockups" / "afterlife-release" / "localization-credits.html"


def _capture_errors(page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )


def _contrast(page, foreground: str, background: str) -> float:
    return page.evaluate(
        """([foreground, background]) => {
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = 1;
          const context = canvas.getContext('2d', {willReadFrequently: true});
          const rgb = value => {
            context.clearRect(0, 0, 1, 1);
            context.fillStyle = value;
            context.fillRect(0, 0, 1, 1);
            return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3);
          };
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

        assert page.locator(".language-choice").count() == 8
        assert page.locator('[data-format-group="clock"]').count() == 2
        assert page.locator('[data-format-group="week"]').count() == 2
        assert page.locator('[data-choice-trigger="region"]').count() == 1
        assert page.locator('[data-choice-trigger="timezone"]').count() == 1
        assert page.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
        assert (
            page.locator('[role="radio"][aria-checked="true"]').first.get_attribute("data-language")
            == "en"
        )
        assert page.locator(".language-choice").first.evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        assert page.locator("#save-locale").evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(".language-choice").first.evaluate(
            "el => parseFloat(getComputedStyle(el).transitionDuration || '0') === 0"
        )

        skip = page.locator(".skip-link")
        skip.focus()
        assert skip.bounding_box()["y"] >= 0
        page.evaluate("document.activeElement.blur()")

        english = page.locator('[data-language="en"]')
        english.focus()
        page.keyboard.press("ArrowDown")
        expect(page.locator('[data-language="fr"]')).to_have_attribute("aria-checked", "true")
        assert page.locator("html").get_attribute("lang") == "fr"
        assert page.locator("html").get_attribute("dir") == "ltr"
        expect(page.locator("#sample-title")).to_have_text("accueil")

        arabic = page.locator('[data-language="ar"]')
        arabic.click()
        expect(arabic).to_have_attribute("aria-checked", "true")
        assert page.locator("html").get_attribute("lang") == "ar"
        assert page.locator("html").get_attribute("dir") == "rtl"
        expect(page.locator("#sample-title")).to_have_text("الرئيسية")
        assert (
            page.locator(".sample-path").evaluate("el => getComputedStyle(el).direction") == "ltr"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )

        region = page.locator("#region-trigger")
        region.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#region-menu")).to_be_visible()
        page.locator('#region-menu [data-value="TW"]').click()
        expect(region).to_have_text("Taiwan")
        expect(page.locator("#preview-region")).to_have_text("TW")
        expect(region).to_be_focused()

        timezone = page.locator("#timezone-trigger")
        timezone.click()
        expect(page.locator("#timezone-menu")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#timezone-menu")).to_be_hidden()
        expect(timezone).to_be_focused()

        auto_clock = page.locator('[data-format-group="clock"][data-format-value="auto"]')
        auto_clock.focus()
        page.keyboard.press("ArrowRight")
        expect(
            page.locator('[data-format-group="clock"][data-format-value="24"]')
        ).to_have_attribute("aria-checked", "true")

        page.locator("#save-locale").click()
        expect(page.locator("#locale-save-state")).to_have_text("saved just now · preview only")
        page.screenshot(path="/tmp/alles-phase10-localization-arabic-desktop.png", full_page=True)

        page.locator('[data-pane-target="credits"]').click()
        expect(page.locator('[data-pane="credits"]')).to_be_visible()
        assert page.locator(".credit-row").count() == 8
        expect(page.locator("#credit-detail h2")).to_have_text("CodeMirror 6")

        service_tab = page.locator('[data-credit-category="service"]')
        service_tab.click()
        assert page.locator(".credit-row").count() == 2
        assert page.locator(".credit-row strong").all_inner_texts() == ["SearXNG", "Actual Budget"]
        page.locator("#credit-search").fill("actual")
        assert page.locator(".credit-row").count() == 1
        page.locator(".credit-row").click()
        expect(page.locator("#credit-detail h2")).to_have_text("Actual Budget")
        expect(page.locator("#credit-detail")).to_contain_text("26.7.0")
        assert page.locator(".credit-source").get_attribute("href") == "https://actualbudget.org"
        page.screenshot(path="/tmp/alles-phase10-credits-desktop.png", full_page=True)

        page.locator("#theme-toggle").click()
        assert page.locator("html").get_attribute("data-theme") == "light"
        body = page.locator("body")
        foreground = body.evaluate("el => getComputedStyle(el).color")
        background = body.evaluate("el => getComputedStyle(el).backgroundColor")
        assert _contrast(page, foreground, background) >= 7
        page.evaluate("document.documentElement.style.zoom = '2'")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.evaluate("document.documentElement.style.zoom = '1'")

        page.locator("#close-preview").click()
        expect(page.locator("#settings-preview")).to_be_hidden()
        expect(page.locator("#reopen-preview")).to_be_focused()
        page.locator("#reopen-preview").click()
        expect(page.locator("#settings-preview")).to_be_visible()
        expect(page.locator("#close-preview")).to_be_focused()
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844}, reduced_motion="reduce"
        )
        page = mobile.new_page()
        _capture_errors(page, errors)
        page.goto(STARTER.as_uri(), wait_until="networkidle")
        assert page.locator(".settings-nav").evaluate(
            "el => getComputedStyle(el).overflowX === 'auto'"
        )
        assert page.locator(".locale-workbench").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
        )
        assert page.locator(".text-action").evaluate(
            "el => el.getBoundingClientRect().width >= 44 && el.getBoundingClientRect().height >= 44"
        )
        page.locator('[data-language="ar"]').click()
        assert page.locator("html").get_attribute("dir") == "rtl"
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path="/tmp/alles-phase10-localization-arabic-mobile.png", full_page=True)
        page.locator('[data-pane-target="credits"]').click()
        assert page.locator(".credits-workbench").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path="/tmp/alles-phase10-credits-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("Phase 10 localization and credits starter browser gate passed")


if __name__ == "__main__":
    run()

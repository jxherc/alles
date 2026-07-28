"""Browser gate for the approved real Home customization Settings pane.

Run against an Alles server backed by throwaway ALLES_DATA. The gate restores
the default Home preferences before it exits.
"""

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("HOME_SETTINGS_BASE", "http://127.0.0.1:8971")


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _capture_errors(page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )


def _section_order(locator) -> list[str]:
    return locator.evaluate_all("rows => rows.map(row => row.dataset.homeSection)")


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


def _open_home_settings(page) -> None:
    page.locator("#today-settings").click()
    expect(page.locator("#settings-modal")).to_be_visible()
    expect(page.locator('.s-nav-item[data-pane="home"]')).to_have_attribute("aria-current", "page")
    expect(page.locator("#s-pane-home")).to_be_visible()
    expect(page.locator("#home-settings-workbench")).to_have_attribute("aria-busy", "false")


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 980},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = desktop.new_page()
        _capture_errors(page, errors)
        page.goto(BASE, wait_until="networkidle")
        expect(page.locator("#today-view")).to_be_visible()

        pinned_apps = page.locator(".today-shortcut-section")
        expect(pinned_apps.locator("h2")).to_have_text("pinned apps")
        pinned_edit = pinned_apps.locator("[data-home-pinned-edit]")
        expect(pinned_edit).to_have_text("edit")
        assert pinned_apps.locator("header > span").count() == 0
        assert pinned_edit.evaluate(
            "el => el.getBoundingClientRect().height >= 36 && el.getBoundingClientRect().width >= 36"
        )
        assert (
            _contrast(
                page,
                pinned_edit.evaluate("el => getComputedStyle(el).color"),
                page.locator("#today-view").evaluate("el => getComputedStyle(el).backgroundColor"),
            )
            >= 4.5
        )
        pinned_edit.click()
        expect(page.locator("#settings-modal")).to_be_visible()
        expect(page.locator("#s-pane-home")).to_be_visible()
        page.locator("#home-settings-reset").click()
        page.locator("#home-settings-save").click()
        expect(page.locator("#home-settings-save-state")).to_have_text("saved just now")
        page.locator("#settings-modal-close").click()
        expect(pinned_apps.locator("[data-home-pinned-edit]")).to_be_focused()

        _open_home_settings(page)
        pane = page.locator("#s-pane-home")
        assert pane.locator("#home-settings-sections > .home-settings-row").count() == 5
        assert pane.locator("#home-settings-shortcuts > .home-settings-row").count() == 9
        assert pane.locator('[role="switch"]').count() == 14
        assert pane.locator('[role="radiogroup"] [role="radio"]').count() == 2
        assert pane.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
        assert pane.locator(".home-settings-switch").first.evaluate(
            "el => el.getBoundingClientRect().width >= 44 && el.getBoundingClientRect().height >= 44"
        )
        assert pane.locator(".home-settings-switch").first.evaluate(
            "el => getComputedStyle(el, '::before').borderRadius === '999px'"
        )
        assert pane.locator(".home-settings-switch").first.evaluate(
            "el => getComputedStyle(el, '::after').borderRadius === '50%'"
        )
        assert pane.locator('[data-home-section="needs_you"] [role="switch"]').is_disabled()

        pane.locator('[data-home-section="needs_you"] [data-home-move="down"]').click()
        assert _section_order(pane.locator("#home-settings-sections > .home-settings-row"))[:2] == [
            "today",
            "needs_you",
        ]

        briefs = pane.locator('[data-home-section="briefs"] [role="switch"]')
        briefs.focus()
        page.keyboard.press("Space")
        expect(briefs).to_have_attribute("aria-checked", "false")

        # Moving between panes must not replace a local draft with a fresh GET.
        page.locator('.s-nav-item[data-pane="models"]').click()
        page.locator('.s-nav-item[data-pane="home"]').click()
        expect(briefs).to_have_attribute("aria-checked", "false")
        expect(page.locator("#home-settings-load-state")).to_have_text("unsaved changes kept here")

        comfortable = pane.locator('[data-home-density="comfortable"]')
        comfortable.focus()
        page.keyboard.press("ArrowRight")
        expect(pane.locator('[data-home-density="compact"]')).to_have_attribute(
            "aria-checked", "true"
        )

        inbox = pane.locator('[data-home-shortcut="inbox"] [role="switch"]')
        inbox.click()
        pane.locator('[data-home-shortcut="inbox"] [data-home-move="up"]').click()

        # A save owns one immutable edit set. Controls remain inert until it settles.
        page.evaluate(
            """() => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = (input, init = {}) => {
                if (String(input).includes('/api/today/preferences') && init.method === 'PUT') {
                  window.fetch = originalFetch;
                  return new Promise(resolve => {
                    window.__releaseHomeSettingsSave = async () => resolve(await originalFetch(input, init));
                  });
                }
                return originalFetch(input, init);
              };
            }"""
        )
        page.locator("#home-settings-save").click()
        expect(page.locator("#home-settings-workbench")).to_have_attribute("aria-busy", "true")
        assert page.locator("#home-settings-workbench").evaluate("el => el.inert")
        page.locator('[data-home-section="briefs"] [role="switch"]').evaluate("el => el.click()")
        expect(briefs).to_have_attribute("aria-checked", "false")
        page.evaluate("window.__releaseHomeSettingsSave()")
        expect(page.locator("#home-settings-save-state")).to_have_text("saved just now")

        page.locator("#settings-modal-close").click()
        expect(page.locator("#settings-modal")).to_be_hidden()
        expect(page.locator("#today-settings")).to_be_focused()
        assert page.locator("#today-sections").evaluate("el => el.classList.contains('compact')")
        rendered = page.locator("#today-sections > [data-home-section]")
        assert rendered.evaluate_all("rows => rows.map(row => row.dataset.homeSection)") == [
            "today",
            "needs_you",
            "in_progress",
            "shortcuts",
        ]
        assert "inbox" in page.locator(".today-shortcuts").inner_text().lower()

        page.reload(wait_until="networkidle")
        assert page.locator("#today-sections").evaluate("el => el.classList.contains('compact')")
        assert page.locator("#today-sections > [data-home-section]").evaluate_all(
            "rows => rows.map(row => row.dataset.homeSection)"
        ) == ["today", "needs_you", "in_progress", "shortcuts"]
        assert "inbox" in page.locator(".today-shortcuts").inner_text().lower()

        _open_home_settings(page)
        page.locator("#home-settings-reset").click()
        expect(page.locator("#home-settings-save-state")).to_contain_text("defaults restored")
        page.locator("#home-settings-save").click()
        expect(page.locator("#home-settings-save-state")).to_have_text("saved just now")

        page.evaluate("document.documentElement.dataset.theme = 'light'")
        foreground = page.locator(".home-settings-copy strong").first.evaluate(
            "el => getComputedStyle(el).color"
        )
        background = page.locator(".home-settings-list").first.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert _contrast(page, foreground, background) >= 4.5
        page.evaluate("document.documentElement.style.zoom = '2'")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.evaluate("document.documentElement.style.zoom = '1'")
        page.locator("#settings-modal .s-content").evaluate("el => { el.scrollTop = 0; }")
        page.screenshot(path="/tmp/alles-real-home-settings-desktop.png", full_page=True)
        page.locator("#settings-modal-close").click()
        page.reload(wait_until="networkidle")
        assert page.locator("#today-sections").evaluate("el => !el.classList.contains('compact')")
        assert page.locator("#today-sections > [data-home-section]").evaluate_all(
            "rows => rows.map(row => row.dataset.homeSection)"
        ) == ["needs_you", "today", "in_progress", "briefs", "shortcuts"]
        assert "inbox" not in page.locator(".today-shortcuts").inner_text().lower()
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = mobile.new_page()
        _capture_errors(page, errors)
        page.goto(BASE, wait_until="networkidle")
        assert page.locator("[data-home-pinned-edit]").evaluate(
            "el => el.getBoundingClientRect().height >= 44 && el.getBoundingClientRect().width >= 44"
        )
        _open_home_settings(page)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator("#settings-modal .s-layout").evaluate(
            "el => getComputedStyle(el).flexDirection === 'column'"
        )
        assert page.locator(".home-settings-workbench").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
        )
        assert page.locator(".home-settings-preview").evaluate(
            "el => getComputedStyle(el).position === 'static'"
        )
        page.route(
            "**/api/today/preferences",
            lambda route: (
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"Home settings could not save"}',
                )
                if route.request.method == "PUT"
                else route.continue_()
            ),
        )
        page.locator('[data-home-section="briefs"] [role="switch"]').click()
        page.locator("#home-settings-save").click()
        expect(page.locator("#home-settings-save-state")).to_have_text(
            "Home settings could not save"
        )
        expect(page.locator("#home-settings-save")).to_be_enabled()
        expected_503 = [error for error in errors if "status of 503 (Service Unavailable)" in error]
        assert len(expected_503) == 1, errors
        errors[:] = [error for error in errors if error not in expected_503]
        page.screenshot(path="/tmp/alles-real-home-settings-mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("Real Home customization Settings browser gate passed")


if __name__ == "__main__":
    run()

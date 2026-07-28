"""Rendered regression gate for the approved real Phase 10 Settings slice.

Run against an Alles server backed by a throwaway ALLES_DATA directory.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("PHASE10_BASE", "http://127.0.0.1:8974")
ROOT = Path(__file__).resolve().parent.parent
LANGUAGES = ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _capture_errors(page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )


def _open_settings_pane(page, pane: str, busy_id: str) -> None:
    if not page.locator("#settings-modal").is_visible():
        if not page.locator("#today-settings").is_visible():
            page.evaluate("window._navigateTo('today')")
            expect(page.locator("#today-settings")).to_be_visible()
        page.locator("#today-settings").click()
        expect(page.locator("#settings-modal")).to_be_visible()
    page.locator(f'.s-nav-item[data-pane="{pane}"]').click()
    expect(page.locator(f"#s-pane-{pane}")).to_be_visible()
    expect(page.locator(busy_id)).to_have_attribute("aria-busy", "false")


def _assert_no_overflow(page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    assert page.locator("#settings-modal .s-content").evaluate(
        "el => el.scrollWidth <= el.clientWidth + 1"
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
    _require_throwaway_data_root()
    errors: list[str] = []
    manifest_entry_count = len(
        json.loads((ROOT / "credits" / "manifest.json").read_text("utf-8"))["entries"]
    )
    catalogs = {
        language: json.loads((ROOT / "static" / "locales" / f"{language}.json").read_text("utf-8"))
        for language in LANGUAGES
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 980},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = desktop.new_page()
        _capture_errors(page, errors)
        dismissed = page.request.post(f"{BASE}/api/setup/dismiss")
        assert dismissed.ok, dismissed.text()
        dark = page.request.put(f"{BASE}/api/appearance", data={"preset": "dark"})
        assert dark.ok, dark.text()
        reset = page.request.patch(
            f"{BASE}/api/settings",
            data={
                "language": "en",
                "region": "",
                "timezone": "",
                "clock_format": "auto",
                "week_start": "auto",
            },
        )
        assert reset.ok, reset.text()
        page.goto(BASE, wait_until="networkidle")
        expect(page.locator("#today-view")).to_be_visible()

        _open_settings_pane(page, "notifications", "#locale-settings-workbench")
        pane = page.locator("#s-pane-notifications")
        assert pane.locator(".locale-language-choice").count() == 8
        assert pane.locator('.locale-language-choice[aria-disabled="false"]').count() == 8
        expect(pane.locator('[data-locale-language="en"]')).to_have_attribute(
            "aria-checked", "true"
        )
        assert pane.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
        expect(page.locator("#s-region-trigger")).to_have_text("automatic")
        expect(page.locator("#s-timezone-trigger")).to_have_text("automatic")
        expect(page.locator("#s-region-detected")).to_contain_text("detected")
        expect(page.locator("#s-timezone-detected")).to_contain_text("detected")

        region = page.locator("#s-region-trigger")
        region.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#s-region-menu")).to_be_visible()
        expect(page.locator('#s-region-menu [aria-selected="true"]')).to_be_focused()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        expect(region).to_have_text("Taiwan")
        expect(region).to_be_focused()
        expect(page.locator("#locale-preview-region")).to_have_text("Taiwan")

        timezone = page.locator("#s-timezone-trigger")
        timezone.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#s-timezone-menu")).to_be_visible()
        expect(page.locator('#s-timezone-menu [aria-selected="true"]')).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#s-timezone-menu")).to_be_hidden()
        expect(timezone).to_be_focused()

        clock_auto = pane.locator('[data-locale-format="clock_format"][data-value="auto"]')
        clock_auto.focus()
        page.keyboard.press("ArrowRight")
        expect(
            pane.locator('[data-locale-format="clock_format"][data-value="24"]')
        ).to_have_attribute("aria-checked", "true")
        week_auto = pane.locator('[data-locale-format="week_start"][data-value="auto"]')
        week_auto.focus()
        page.keyboard.press("ArrowRight")
        expect(
            pane.locator('[data-locale-format="week_start"][data-value="mon"]')
        ).to_have_attribute("aria-checked", "true")

        for language in LANGUAGES:
            catalog = catalogs[language]["messages"]
            row = pane.locator(f'[data-locale-language="{language}"]')
            row.focus()
            page.keyboard.press("Space")
            expect(row).to_have_attribute("aria-checked", "true")
            save = page.locator("#s-locale-save")
            save.focus()
            page.keyboard.press("Enter")
            expect(page.locator("#locale-settings-save-state")).to_have_text(
                catalog["locale.saved_now"]
            )
            expect(page.locator("html")).to_have_attribute(
                "lang", re.compile(rf"^{re.escape(language)}(?:-|$)", re.IGNORECASE)
            )
            expect(page.locator("html")).to_have_attribute(
                "dir", "rtl" if language == "ar" else "ltr"
            )
            if language == "ar":
                assert page.locator("#locale-preview-path").evaluate(
                    "el => getComputedStyle(el).direction === 'ltr' && getComputedStyle(el).unicodeBidi === 'isolate'"
                )
            expect(pane).to_be_visible()
            expect(save).to_be_focused()
            expect(save).to_have_text(catalog["locale.save"])
            for theme in ("dark", "light"):
                page.locator("html").evaluate("(el, value) => { el.dataset.theme = value; }", theme)
                _assert_no_overflow(page)
            page.evaluate("document.documentElement.style.zoom = '2'")
            _assert_no_overflow(page)
            page.evaluate("document.documentElement.style.zoom = '1'")

            page.locator("#settings-modal-close").click()
            expect(page.locator("#today-settings")).to_be_focused()
            expect(page.locator("#today-settings")).to_have_text(catalog["common.settings"])
            expect(page.locator("#today-capture-input")).to_have_attribute(
                "placeholder", catalog["home.capture_placeholder"]
            )
            page.evaluate("window._navigateTo('andromeda')")
            expect(page.locator("#andromeda-view")).to_be_visible()
            expect(page.locator("#andromeda-query")).to_have_attribute(
                "placeholder", catalog["andromeda.search_web"]
            )
            page.evaluate("window._navigateTo('tasks')")
            expect(page.locator("#tasks-view")).to_be_visible()
            expect(page.locator("#tasks-view .page-view-title")).to_have_text(
                catalog["tasks.title"]
            )
            sample = {
                "ar": "مهمة جديدة",
                "zh-Hans": "新任务",
                "zh-Hant": "新任務",
                "ja": "新しいタスク",
                "ko": "새 작업",
            }.get(language, "localized task")
            task_input = page.locator("#task-add-input")
            task_input.fill(sample)
            task_input.press("End")
            assert task_input.evaluate("el => el.selectionStart === el.value.length")
            page.keyboard.insert_text("!")
            assert task_input.input_value().endswith("!")
            task_input.press("Home")
            page.keyboard.insert_text("?")
            assert task_input.input_value().startswith("?")
            assert task_input.evaluate("el => getComputedStyle(el).direction") == (
                "rtl" if language == "ar" else "ltr"
            )
            task_input.fill("")
            page.evaluate("window._navigateTo('calendar')")
            expect(page.locator("#calendar-view")).to_be_visible()
            expect(page.locator('#cal-view [data-view="month"]')).to_have_text(
                catalog["calendar.month"]
            )
            page.evaluate("window._navigateTo('chat')")
            expect(page.locator("#composer-ta")).to_be_visible()
            expect(page.locator("#composer-ta")).to_have_attribute(
                "placeholder", catalog["aide.message_placeholder"]
            )
            expect(page.locator("#aide-conversation-name")).to_have_text(catalog["aide.new_task"])
            expect(page.locator("#aide-project-context-label")).to_have_text(catalog["tasks.title"])
            expect(page.locator("#perm-mode-btn .perm-label")).to_have_text("auto mode")
            expect(page.locator("#effort-btn .effort-label")).to_have_text(
                catalog["aide.effort_medium"]
            )
            greeting = page.locator("#welcome-greeting").inner_text().strip()
            translated_greetings = {
                value for key, value in catalog.items() if key.startswith("home.greeting.")
            }
            assert greeting in translated_greetings, (language, greeting)
            desktop.set_offline(True)
            page.evaluate("window._navigateTo('andromeda')")
            expect(page.locator("#andromeda-query")).to_have_attribute(
                "placeholder", catalog["andromeda.search_web"]
            )
            desktop.set_offline(False)
            if language in {"zh-Hans", "ja", "ar"}:
                page.locator("#toast-container").evaluate("el => el.replaceChildren()")
                page.screenshot(path=f"/tmp/alles-phase10-{language}-desktop.png", full_page=True)
            page.evaluate("window._navigateTo('today')")
            _open_settings_pane(page, "notifications", "#locale-settings-workbench")

        reset_language = page.request.patch(f"{BASE}/api/settings", data={"language": "en"})
        assert reset_language.ok, reset_language.text()
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", re.compile(r"^en(?:-|$)"))
        _open_settings_pane(page, "notifications", "#locale-settings-workbench")

        page.locator("#s-locale-save").click()
        expect(page.locator("#locale-settings-save-state")).to_have_text("saved just now")
        saved = page.request.get(f"{BASE}/api/settings").json()
        assert saved["language"] == "en"
        assert saved["region"] == "TW"
        assert saved["timezone"] == ""
        assert saved["clock_format"] == "24"
        assert saved["week_start"] == "mon"
        expect(page.locator("html")).to_have_attribute("lang", re.compile(r"^en(?:-TW)?$"))
        expect(page.locator("html")).to_have_attribute("dir", "ltr")

        page.locator("#settings-modal-close").click()
        expect(page.locator("#today-settings")).to_be_focused()
        _open_settings_pane(page, "notifications", "#locale-settings-workbench")
        expect(page.locator("#s-region-trigger")).to_have_text("Taiwan")
        expect(
            pane.locator('[data-locale-format="clock_format"][data-value="24"]')
        ).to_have_attribute("aria-checked", "true")
        expect(
            pane.locator('[data-locale-format="week_start"][data-value="mon"]')
        ).to_have_attribute("aria-checked", "true")

        page.locator("#settings-modal .s-content").evaluate("el => { el.scrollTop = 0; }")
        page.screenshot(path="/tmp/alles-phase10-real-localization-desktop.png", full_page=True)

        _open_settings_pane(page, "credits", "#credits-settings-workbench")
        credits = page.locator("#s-pane-credits")
        expect(page.locator('label[for="credits-search"]')).to_have_css("position", "absolute")
        assert credits.locator(".credits-row").count() == manifest_entry_count
        expect(page.locator("#credits-coverage")).to_contain_text("manifest coverage complete")
        expect(page.locator("#credits-summary")).to_contain_text(
            f"{manifest_entry_count} entries shown"
        )

        all_tab = credits.locator('[data-credit-category="all"]')
        all_tab.focus()
        page.keyboard.press("ArrowRight")
        expect(credits.locator('[data-credit-category="code"]')).to_have_attribute(
            "aria-selected", "true"
        )
        expect(credits.locator('[data-credit-category="code"]')).to_be_focused()
        assert 0 < credits.locator(".credits-row").count() < manifest_entry_count

        page.locator("#credits-search").fill("xterm")
        assert credits.locator(".credits-row").count() == 2
        row = credits.locator('[data-credit-id="xterm-js"]')
        row.click()
        expect(row).to_be_focused()
        expect(page.locator("#credits-detail h3")).to_have_text("xterm.js")
        expect(page.locator("#credits-detail .credits-source")).to_have_attribute(
            "href", "https://github.com/xtermjs/xterm.js"
        )
        assert page.locator("#credits-detail .credits-license").count() == 1
        page.locator("#credits-detail .credits-license summary").first.click()
        expect(page.locator("#credits-detail .credits-license pre").first).to_contain_text(
            "Permission is hereby granted"
        )
        page.locator("#credits-search").fill("no such dependency")
        expect(page.locator("#credits-list .credits-empty")).to_have_text(
            "No credits match this search."
        )
        expect(page.locator("#credits-detail")).to_contain_text("No credits match this search.")
        page.locator("#credits-search").fill("xterm")

        dark_background = page.locator("body").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert dark_background == "rgb(10, 10, 10)", dark_background
        page.locator('.s-nav-item[data-pane="themes"]').click()
        expect(page.locator("#s-pane-themes")).to_be_visible()
        page.locator('.theme-mode-btn[data-theme-mode="light"]').click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        expect(page.locator("body")).to_have_css("background-color", "rgb(245, 244, 241)")
        _open_settings_pane(page, "credits", "#credits-settings-workbench")
        foreground = page.locator("#credits-detail h3").evaluate("el => getComputedStyle(el).color")
        background = page.locator("#settings-modal .s-modal").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert _contrast(page, foreground, background) >= 4.5
        page.evaluate("document.documentElement.style.zoom = '2'")
        _assert_no_overflow(page)
        page.evaluate("document.documentElement.style.zoom = '1'")
        _assert_no_overflow(page)
        page.screenshot(path="/tmp/alles-phase10-real-credits-desktop.png", full_page=True)
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = mobile.new_page()
        _capture_errors(page, errors)
        for language in LANGUAGES:
            selected = page.request.patch(f"{BASE}/api/settings", data={"language": language})
            assert selected.ok, selected.text()
            page.goto(BASE, wait_until="networkidle")
            catalog = catalogs[language]["messages"]
            expect(page.locator("html")).to_have_attribute(
                "lang", re.compile(rf"^{re.escape(language)}(?:-|$)", re.IGNORECASE)
            )
            expect(page.locator("html")).to_have_attribute(
                "dir", "rtl" if language == "ar" else "ltr"
            )
            _open_settings_pane(page, "notifications", "#locale-settings-workbench")
            locale_columns = page.locator(".locale-settings-workbench").evaluate(
                "el => getComputedStyle(el).gridTemplateColumns"
            )
            assert len(locale_columns.split()) == 1, locale_columns
            assert page.locator(".locale-settings-preview").evaluate(
                "el => getComputedStyle(el).position === 'static' && getComputedStyle(el).order === '-1'"
            )
            assert page.locator("#s-region-trigger").evaluate(
                "el => el.getBoundingClientRect().height >= 44"
            )
            assert page.locator(".locale-language-choice").first.evaluate(
                "el => el.getBoundingClientRect().height >= 44"
            )
            page.evaluate("document.documentElement.style.zoom = '2'")
            _assert_no_overflow(page)
            page.evaluate("document.documentElement.style.zoom = '1'")
            _assert_no_overflow(page)
            page.locator("#settings-modal-close").click()
            page.evaluate("window._navigateTo('andromeda')")
            expect(page.locator("#andromeda-query")).to_have_attribute(
                "placeholder", catalog["andromeda.search_web"]
            )
            _assert_no_overflow(page)
            page.evaluate("window._navigateTo('tasks')")
            expect(page.locator("#tasks-view .page-view-title")).to_have_text(
                catalog["tasks.title"]
            )
            _assert_no_overflow(page)
            page.evaluate("window._navigateTo('calendar')")
            expect(page.locator('#cal-view [data-view="month"]')).to_have_text(
                catalog["calendar.month"]
            )
            _assert_no_overflow(page)
            page.evaluate("window._navigateTo('chat')")
            expect(page.locator("#composer-ta")).to_have_attribute(
                "placeholder", catalog["aide.message_placeholder"]
            )
            expect(page.locator("#aide-conversation-name")).to_have_text(catalog["aide.new_task"])
            expect(page.locator("#perm-mode-btn .perm-label")).to_have_text("auto mode")
            expect(page.locator("#effort-btn .effort-label")).to_have_text(
                catalog["aide.effort_medium"]
            )
            _assert_no_overflow(page)
            if language in {"zh-Hant", "ko", "ar"}:
                page.locator("#toast-container").evaluate("el => el.replaceChildren()")
                page.screenshot(path=f"/tmp/alles-phase10-{language}-mobile.png", full_page=True)
        selected = page.request.patch(f"{BASE}/api/settings", data={"language": "en"})
        assert selected.ok, selected.text()
        page.goto(BASE, wait_until="networkidle")
        page.screenshot(path="/tmp/alles-phase10-real-localization-mobile.png", full_page=True)

        page.route(
            "**/api/credits",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"credits temporarily unavailable"}',
            ),
        )
        _open_settings_pane(page, "credits", "#credits-settings-workbench")
        expect(page.locator("#credits-settings-load-state")).to_have_text("credits unavailable")
        expect(page.locator("#credits-coverage")).to_contain_text("Credits could not load")
        expect(page.locator("#credits-coverage [data-credits-retry]")).to_be_visible()
        page.unroute("**/api/credits")
        page.locator("#credits-coverage [data-credits-retry]").click()
        expect(page.locator("#credits-settings-load-state")).to_have_text("inventory complete")
        expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
        credits_columns = page.locator(".credits-settings-workbench").evaluate(
            "el => getComputedStyle(el).gridTemplateColumns"
        )
        assert len(credits_columns.split()) == 1, credits_columns
        assert page.locator(".credits-row").first.evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        _assert_no_overflow(page)
        page.screenshot(path="/tmp/alles-phase10-real-credits-mobile.png", full_page=True)
        mobile.close()

        offline = browser.new_context(
            viewport={"width": 960, "height": 760},
            reduced_motion="reduce",
            service_workers="allow",
        )
        page = offline.new_page()
        _capture_errors(page, errors)
        selected = page.request.patch(f"{BASE}/api/settings", data={"language": "en"})
        assert selected.ok, selected.text()
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function(
            "() => navigator.serviceWorker && navigator.serviceWorker.controller",
            timeout=15_000,
        )
        page.wait_for_timeout(1_000)
        cached_locales = page.evaluate(
            """async () => {
              const keys = [];
              for (const name of await caches.keys()) {
                const cache = await caches.open(name);
                keys.push(...(await cache.keys()).map(request => new URL(request.url).pathname));
              }
              return [...new Set(keys.filter(path => path.startsWith('/static/locales/')))];
            }"""
        )
        expected_locales = {f"/static/locales/{language}.json" for language in LANGUAGES}
        assert expected_locales.issubset(set(cached_locales)), cached_locales
        for language in LANGUAGES:
            offline.set_offline(False)
            selected = page.request.patch(f"{BASE}/api/settings", data={"language": language})
            assert selected.ok, selected.text()
            page.goto(BASE, wait_until="networkidle")
            catalog = catalogs[language]["messages"]
            expect(page.locator("#today-view")).to_be_visible()
            offline.set_offline(True)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_function(
                "() => !document.body.classList.contains('preboot')",
                timeout=10_000,
            )
            expect(page.locator("#today-view")).to_be_visible()
            expect(page.locator("html")).to_have_attribute(
                "lang", re.compile(rf"^{re.escape(language)}(?:-|$)", re.IGNORECASE)
            )
            expect(page.locator("html")).to_have_attribute(
                "dir", "rtl" if language == "ar" else "ltr"
            )
            expect(page.locator("#today-capture-input")).to_have_attribute(
                "placeholder", catalog["home.capture_placeholder"]
            )
        offline.set_offline(False)
        offline.close()
        browser.close()

    expected_503 = [error for error in errors if "status of 503 (Service Unavailable)" in error]
    assert len(expected_503) == 1, errors
    errors[:] = [error for error in errors if error not in expected_503]
    expected_offline = [error for error in errors if "net::ERR_INTERNET_DISCONNECTED" in error]
    errors[:] = [error for error in errors if error not in expected_offline]
    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print(
        "Real Phase 10 language and Credits Settings gate passed desktop, mobile, keyboard, persistence, cold offline reload, RTL isolation, 200% zoom, light/dark tokens, reduced motion, overflow, and clean console"
    )


if __name__ == "__main__":
    run()

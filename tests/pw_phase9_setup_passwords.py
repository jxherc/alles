"""Rendered Phase 9 setup and Passwords browser-access gate.

Run only against a server using an owned throwaway ``ALLES_DATA`` root.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Page, expect, sync_playwright

PORT = os.environ.get("PORT", "8059")
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "")
OUTPUT: Path
EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


def _verify_test_root() -> None:
    if os.environ.get("ALLES_TEST_DATA") != "1" or not RUN_ID:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if (
        DATA == Path(tempfile.gettempdir()).resolve()
        or Path(tempfile.gettempdir()).resolve() not in DATA.parents
    ):
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, RUN_ID)


def _capture_errors(page: Page, errors: list[str], label: str) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"{label} console: {message.text}") if message.type == "error" else None
        ),
    )


def _assert_no_page_overflow(page: Page) -> None:
    metrics = page.evaluate(
        """() => ({
          document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          body: document.body.scrollWidth - document.body.clientWidth,
        })"""
    )
    assert metrics["document"] <= 1, metrics


def _assert_targets(page: Page, selector: str) -> None:
    failures = page.locator(selector).evaluate_all(
        """elements => elements.filter(element => {
          const style = getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden' || element.disabled) return false;
          const box = element.getBoundingClientRect();
          return box.width < 43.5 || box.height < 43.5;
        }).map(element => ({ label: element.textContent.trim() || element.getAttribute('aria-label'), box: element.getBoundingClientRect().toJSON() }))"""
    )
    assert not failures, failures


def _assert_setup_clears_shell(page: Page) -> None:
    setup_box = page.locator("#setup-wizard").bounding_box()
    card_box = page.locator("#setup-wizard .setup-card").bounding_box()
    assert setup_box is not None and setup_box["x"] >= 51.5, setup_box
    assert card_box is not None and card_box["x"] >= setup_box["x"], {
        "setup": setup_box,
        "card": card_box,
    }
    assert card_box["x"] + card_box["width"] <= setup_box["x"] + setup_box["width"] + 1
    gutters = page.locator("#setup-wizard .setup-body").evaluate(
        """element => {
          const style = getComputedStyle(element);
          return { left: parseFloat(style.paddingLeft), right: parseFloat(style.paddingRight) };
        }"""
    )
    assert gutters["left"] >= 8 and gutters["right"] >= 8, gutters


def _set_light_theme(page: Page) -> None:
    page.evaluate(
        """() => {
          const colors = {
            bg: '#f5f4f1', text: '#111111', panel: '#efede9',
            faint: '#d4d2ce', accent: '#737bd9', muted: '#626262',
          };
          const root = document.documentElement;
          Object.entries(colors).forEach(([name, value]) => root.style.setProperty(`--${name}`, value));
          root.dataset.theme = 'light';
          localStorage.setItem('alles-appearance', JSON.stringify({
            preset: 'light', colors, font: 'sans', density: 'comfortable', bgPattern: 'none', frosted: false,
          }));
        }"""
    )


def _contrast(page: Page, foreground: str, background: str) -> float:
    return page.evaluate(
        """([foreground, background]) => {
          const rgb = value => {
            const channels = value.match(/[\\d.]+/g).slice(0, 3).map(Number);
            return value.startsWith('color(srgb') ? channels.map(channel => channel * 255) : channels;
          };
          const lum = value => rgb(value).map(channel => {
            const n = channel / 255;
            return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
          const a = lum(foreground), b = lum(background);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        }""",
        [foreground, background],
    )


def _unlock_passwords(page: Page, password: str) -> None:
    page.evaluate("window._navigateTo('vault')")
    expect(page.locator("#vault-view")).to_be_visible()
    page.locator("#vault-pw-input").fill(password)
    page.locator("#vault-unlock-btn").click()
    expect(page.locator("#vault-unlocked")).to_be_visible()


def run() -> None:
    global OUTPUT

    _verify_test_root()
    OUTPUT = Path(tempfile.mkdtemp(prefix="phase9-browser-artifacts-", dir=DATA))
    errors: list[str] = []
    vault_password = "phase9-browser-master"
    vault_path = DATA / "visible" / "Vault"
    files_path = DATA / "visible" / "Files"
    revised_files_path = DATA / "visible" / "Files revised"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 980},
            reduced_motion="reduce",
            service_workers="block",
            accept_downloads=True,
            locale="zh-Hant-TW",
        )
        page = desktop.new_page()
        _capture_errors(page, errors, "desktop")
        page.goto(BASE, wait_until="networkidle")
        setup = page.locator("#setup-wizard")
        expect(setup).to_be_visible()
        expect(page.locator("#setup-dots")).to_contain_text("1 / 5")
        assert page.locator("#sw-region").count() == 0
        expect(page.locator("#sw-region-status")).to_contain_text(
            "region TW is detected automatically"
        )
        assert (
            _contrast(
                page,
                page.locator(".setup-sub").evaluate("el => getComputedStyle(el).color"),
                page.locator(".setup-card").evaluate("el => getComputedStyle(el).backgroundColor"),
            )
            >= 4.5
        )
        assert setup.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
        _assert_setup_clears_shell(page)
        _assert_targets(page, "#setup-wizard button:visible, #setup-wizard input:visible")
        page.screenshot(path=str(OUTPUT / "setup-basics-desktop.png"), full_page=True)
        page.evaluate("document.documentElement.style.zoom = '2'")
        _assert_no_page_overflow(page)
        assert page.locator(".setup-card").evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        )
        page.evaluate("document.documentElement.style.zoom = '1'")

        basics_mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
            locale="zh-Hant-TW",
        )
        basics_mobile_page = basics_mobile.new_page()
        _capture_errors(basics_mobile_page, errors, "mobile basics")
        basics_mobile_page.goto(BASE, wait_until="networkidle")
        _set_light_theme(basics_mobile_page)
        expect(basics_mobile_page.locator("#setup-dots")).to_contain_text("1 / 5")
        assert basics_mobile_page.locator("#sw-region").count() == 0
        expect(basics_mobile_page.locator("#sw-region-status")).to_contain_text(
            "region TW is detected automatically"
        )
        assert (
            _contrast(
                basics_mobile_page,
                basics_mobile_page.locator(".setup-sub").evaluate(
                    "el => getComputedStyle(el).color"
                ),
                basics_mobile_page.locator(".setup-card").evaluate(
                    "el => getComputedStyle(el).backgroundColor"
                ),
            )
            >= 4.5
        )
        _assert_no_page_overflow(basics_mobile_page)
        _assert_setup_clears_shell(basics_mobile_page)
        _assert_targets(
            basics_mobile_page,
            "#setup-wizard button:visible, #setup-wizard input:visible",
        )
        basics_mobile_page.screenshot(
            path=str(OUTPUT / "setup-basics-mobile-light.png"), full_page=True
        )
        basics_mobile.close()

        # The dialog loops keyboard focus and persists a real paused state on exit.
        page.locator("#setup-skip").focus()
        page.keyboard.press("Shift+Tab")
        expect(page.locator("#sw-save")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator("#setup-skip")).to_be_focused()
        page.locator("#setup-skip").click()
        expect(setup).to_be_hidden()
        assert page.request.get(f"{BASE}/api/setup/status").json()["setup"]["dismissed"]

        page.reload(wait_until="networkidle")
        expect(setup).to_be_hidden()
        page.evaluate("window._openSettings('backup')")
        expect(page.locator("#settings-modal")).to_be_visible()
        expect(page.locator("#setup-resume-status")).to_contain_text("paused")
        page.locator("#setup-resume-btn").click()
        expect(page.locator("#settings-modal")).to_be_hidden()
        expect(setup).to_be_visible()
        assert not page.request.get(f"{BASE}/api/setup/status").json()["setup"]["dismissed"]

        page.locator("#sw-name").fill("owner")
        page.locator("#sw-timezone").fill("Asia/Taipei")
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
        assert page.request.get(f"{BASE}/api/setup/status").json()["setup"]["region"] == "TW"

        access = page.locator('#sw-access [role="radio"]').first
        access.focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator('#sw-access [data-value="lan"]')).to_have_attribute(
            "aria-checked", "true"
        )
        page.keyboard.press("End")
        expect(page.locator('#sw-access [data-value="public"]')).to_have_attribute(
            "aria-checked", "true"
        )
        page.keyboard.press("Home")
        expect(access).to_have_attribute("aria-checked", "true")
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("3 / 5")

        keep_switch = page.locator("#sw-keep-vault")
        expect(keep_switch).to_have_attribute("aria-checked", "true")
        assert keep_switch.evaluate(
            "el => getComputedStyle(el, '::before').borderRadius === '999px' && getComputedStyle(el, '::after').borderRadius === '50%'"
        )
        page.locator("#sw-vault").fill(str(vault_path))
        page.locator("#sw-files").fill(str(files_path))
        page.locator("#sw-vault").evaluate("element => element.setSelectionRange(0, 0)")
        page.locator("#sw-files").evaluate("element => element.setSelectionRange(0, 0)")
        page.locator("#sw-files").blur()
        page.screenshot(path=str(OUTPUT / "setup-files-desktop.png"), full_page=True)

        # A second browser resumes the same server-owned step at mobile width and light theme.
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
        )
        mobile_page = mobile.new_page()
        _capture_errors(mobile_page, errors, "mobile setup")
        mobile_page.goto(BASE, wait_until="networkidle")
        _set_light_theme(mobile_page)
        expect(mobile_page.locator("#setup-dots")).to_contain_text("3 / 5")
        mobile_page.locator("#sw-vault").fill(str(vault_path))
        mobile_page.locator("#sw-files").fill(str(files_path))
        mobile_page.locator("#sw-vault").evaluate("element => element.setSelectionRange(0, 0)")
        mobile_page.locator("#sw-files").evaluate("element => element.setSelectionRange(0, 0)")
        mobile_page.locator("#sw-files").blur()
        _assert_no_page_overflow(mobile_page)
        _assert_targets(mobile_page, "#setup-wizard button:visible, #setup-wizard input:visible")
        assert mobile_page.locator(".setup-choice-group").count() == 0
        title_color = mobile_page.locator(".setup-title").evaluate(
            "el => getComputedStyle(el).color"
        )
        background = mobile_page.locator(".setup-card").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert _contrast(mobile_page, title_color, background) >= 4.5
        mobile_page.screenshot(path=str(OUTPUT / "setup-files-mobile-light.png"), full_page=True)
        mobile.close()

        page.locator("#sw-save").click()
        expect(page.locator("#sw-obsidian")).to_contain_text("nothing was added automatically")
        assert not (vault_path / ".obsidian").exists()
        page.locator("#sw-files").fill(str(revised_files_path))
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("3 / 5")
        expect(page.locator("#sw-obsidian")).to_contain_text("nothing was added automatically")
        assert page.request.get(f"{BASE}/api/setup/status").json()["setup"]["files_preview"] == str(
            revised_files_path
        )
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("4 / 5")

        search = page.locator('#sw-search [role="radio"]').first
        search.focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator("#sw-searxng-url")).to_be_visible()
        page.locator("#sw-searxng-url").fill("https://search.example.com")
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("5 / 5")
        page.locator("#sw-back").click()
        expect(page.locator("#setup-dots")).to_contain_text("4 / 5")
        expect(page.locator('#sw-search [data-value="searxng"]')).to_have_attribute(
            "aria-checked", "true"
        )
        expect(page.locator("#sw-searxng-url")).to_have_value("https://search.example.com")
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_contain_text("5 / 5")

        backup_switch = page.locator("#sw-auto-backup")
        backup_switch.click()
        expect(backup_switch).to_have_attribute("aria-checked", "true")
        backup_switch.click()
        expect(backup_switch).to_have_attribute("aria-checked", "false")
        page.locator("#sw-save").click()
        expect(page.locator("#setup-dots")).to_have_text("setup complete")
        page.screenshot(path=str(OUTPUT / "setup-complete-desktop.png"), full_page=True)
        page.locator("#sw-start").click()
        expect(setup).to_be_hidden()
        completed = page.request.get(f"{BASE}/api/setup/status").json()["setup"]
        assert completed["completed"] and completed["completed_steps"] == [
            "basics",
            "access",
            "files",
            "ai_search",
            "protection",
        ]

        # Passwords shows and owns the exact pairing/unlock lifecycle.
        _unlock_passwords(page, vault_password)
        web_unlock = page.request.post(
            f"{BASE}/api/vault/unlock", data={"password": vault_password}
        )
        vault_token = web_unlock.json()["token"]
        created = page.request.post(
            f"{BASE}/api/vault",
            headers={"X-Vault-Token": vault_token},
            data={
                "name": "Example account",
                "type": "login",
                "username": "owner@example.test",
                "fields": {
                    "username": "owner@example.test",
                    "password": "one selected secret",
                    "url": "https://accounts.example.test/login",
                },
            },
        )
        assert created.ok

        extension = playwright.request.new_context(
            base_url=BASE, extra_http_headers={"Origin": EXTENSION_ORIGIN}
        )
        pairing_response = extension.post(
            "/api/auth/browser/pair/start", data={"name": "phase 9 chromium"}
        )
        assert pairing_response.ok
        pairing = pairing_response.json()

        page.locator("#vault-manage-btn").click()
        modal = page.locator(".vault-modal")
        expect(modal).to_be_visible()
        expect(page.locator("#mv-x")).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(page.locator("#mv-close")).to_be_focused()
        page.locator("#mv-x").focus()
        expect(page.locator(".mv-browser-code").filter(has_text=pairing["code"])).to_be_visible()
        assert (
            page.locator(
                '#vault-browser-access select, #vault-browser-access input[type="checkbox"], #vault-browser-access input[type="radio"]'
            ).count()
            == 0
        )
        _assert_targets(
            page,
            "#vault-browser-access button:visible, #mv-2fa",
        )
        page.screenshot(path=str(OUTPUT / "passwords-pairing-desktop.png"), full_page=True)

        with page.expect_download() as download_info:
            page.locator("#mv-browser-download").click()
        download = download_info.value
        assert download.suggested_filename == "alles-passwords-extension.zip"
        download.save_as(OUTPUT / download.suggested_filename)

        pairing_button = page.locator(f'[data-browser-pair="{pairing["pairing_id"]}"]')
        pairing_button.click()
        expect(pairing_button).to_have_count(0)
        expect(page.locator("#mv-browser-content [data-browser-revoke]")).to_have_count(1)
        paired_response = extension.post(
            "/api/auth/browser/pair/poll",
            data={
                "pairing_id": pairing["pairing_id"],
                "pairing_secret": pairing["pairing_secret"],
            },
        )
        assert paired_response.ok
        connection = paired_response.json()

        unlock_response = extension.post(
            "/api/auth/browser/unlock/start",
            data={
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        assert unlock_response.ok
        unlock_request = unlock_response.json()
        page.locator("#mv-browser-refresh").click()
        expect(
            page.locator(".mv-browser-code").filter(has_text=unlock_request["code"])
        ).to_be_visible()
        page.locator(f'[data-browser-unlock="{unlock_request["request_id"]}"]').click()
        expect(page.locator("#mv-browser-content")).to_contain_text("access active")
        unlocked_response = extension.post(
            "/api/auth/browser/unlock/poll",
            data={
                "request_id": unlock_request["request_id"],
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        session_token = unlocked_response.json()["session_token"]
        page_body = {
            "connection_id": connection["connection_id"],
            "device_secret": connection["device_secret"],
            "session_token": session_token,
            "page_url": "https://accounts.example.test/login",
            "top_url": "https://accounts.example.test/login",
            "frame_url": "https://accounts.example.test/login",
        }
        matches = extension.post("/api/auth/browser/match", data=page_body)
        assert matches.ok and matches.json()["matches"] == [
            {
                "id": created.json()["id"],
                "name": "Example account",
                "username": "owner@example.test",
            }
        ]
        assert "one selected secret" not in matches.text()
        release = extension.post(
            "/api/auth/browser/release",
            data={**page_body, "entry_id": created.json()["id"]},
        )
        assert release.ok and release.json()["password"] == "one selected secret"

        page.locator(f'[data-browser-lock="{connection["connection_id"]}"]').click()
        expect(page.locator(".mv-browser-state")).to_have_text("locked")
        denied = extension.post("/api/auth/browser/match", data=page_body)
        assert denied.status == 403 and denied.json()["code"] == "browser_locked"
        page.locator(f'[data-browser-revoke="{connection["connection_id"]}"]').click()
        page.locator("[data-dialog-confirm]").click()
        expect(page.locator("#mv-browser-content")).to_contain_text("no browsers connected")
        revoked = extension.post(
            "/api/auth/browser/unlock/start",
            data={
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        assert revoked.status == 403 and revoked.json()["code"] == "browser_not_connected"

        page.evaluate("document.documentElement.style.zoom = '2'")
        _assert_no_page_overflow(page)
        assert page.locator(".vault-modal-card").evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        )
        page.evaluate("document.documentElement.style.zoom = '1'")
        page.locator("#mv-close").click()
        expect(page.locator("#vault-manage-btn")).to_be_focused()

        legacy = page.request.get(
            f"{BASE}/api/vault/match?domain=accounts.example.test",
            headers={"X-Vault-Token": vault_token},
        )
        assert legacy.status == 410 and "one selected secret" not in legacy.text()
        extension.dispose()

        # The final empty state reflows on a real mobile Passwords surface in light mode.
        mobile_passwords = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
        )
        mobile_page = mobile_passwords.new_page()
        _capture_errors(mobile_page, errors, "mobile passwords")
        mobile_page.goto(BASE, wait_until="networkidle")
        _set_light_theme(mobile_page)
        _unlock_passwords(mobile_page, vault_password)
        mobile_page.locator("#vault-manage-btn").click()
        expect(mobile_page.locator("#vault-browser-access")).to_be_visible()
        mobile_page.locator("#vault-browser-access").scroll_into_view_if_needed()
        _assert_no_page_overflow(mobile_page)
        _assert_targets(
            mobile_page,
            "#vault-browser-access button:visible, #mv-2fa",
        )
        mobile_page.screenshot(path=str(OUTPUT / "passwords-browsers-mobile-light.png"))
        mobile_passwords.close()
        desktop.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print(f"Phase 9 setup and Passwords browser gate passed; captures: {OUTPUT}")


if __name__ == "__main__":
    run()

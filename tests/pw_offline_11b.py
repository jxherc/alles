"""Rendered PWA install, offline-shell, shortcut, and reconnect gate.

Run only against a server using an owned throwaway ``ALLES_DATA`` root.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Page, expect, sync_playwright

PORT = os.environ.get("PORT", "8879")
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "")
OUTPUT: Path
EXPECTED_OFFLINE_ERRORS = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "Failed to fetch",
    "Load failed",
)


def _verify_test_root() -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or not RUN_ID:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if DATA == temp_root or temp_root not in DATA.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, RUN_ID)


def _capture_errors(
    page: Page,
    errors: list[str],
    failed_requests: list[str],
    offline: dict[str, bool],
) -> None:
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))
    page.on(
        "requestfailed",
        lambda request: failed_requests.append(
            f"{request.method} {request.url}: {request.failure}"
        ),
    )

    def on_console(message) -> None:
        if message.type != "error":
            return
        if offline["active"] and any(token in message.text for token in EXPECTED_OFFLINE_ERRORS):
            return
        errors.append(f"console: {message.text}")

    page.on("console", on_console)


def _assert_shell(page: Page, space: str) -> None:
    expect(page.locator("html")).to_have_attribute("data-kokuen-version", "5")
    body_attribute = "data-space" if space in {"home", "aide", "andromeda"} else "data-app"
    expect(page.locator("body")).to_have_attribute(body_attribute, space)
    expect(page.locator("#app-drawer-btn")).to_be_visible()
    assert (
        page.locator(
            'select:visible, input[type="checkbox"]:visible, input[type="radio"]:visible'
        ).count()
        == 0
    )
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, overflow


def run() -> None:
    global OUTPUT

    _verify_test_root()
    OUTPUT = Path(tempfile.mkdtemp(prefix="pwa-browser-artifacts-", dir=DATA))
    errors: list[str] = []
    failed_requests: list[str] = []
    offline = {"active": False}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            locale="zh-Hant-TW",
        )
        page = context.new_page()
        _capture_errors(page, errors, failed_requests, offline)

        page.goto(f"{BASE}/?app=plan", wait_until="domcontentloaded")
        setup = page.locator("#setup-wizard")
        if setup.is_visible():
            page.locator("#setup-skip").click()
            expect(setup).to_be_hidden()
        page.wait_for_function(
            "() => navigator.serviceWorker && navigator.serviceWorker.controller",
            timeout=15_000,
        )
        expect(page.locator("body")).not_to_have_class("preboot")
        _assert_shell(page, "plan")

        cached = page.evaluate(
            """async () => {
              const names = await caches.keys();
              const urls = [];
              for (const name of names) {
                const cache = await caches.open(name);
                urls.push(...(await cache.keys()).map(request => request.url));
              }
              return { names, urls };
            }"""
        )
        assert cached["names"] == ["alles-v258"], cached["names"]
        assert any(url.endswith("/") for url in cached["urls"])
        assert any("/static/style.css?v=303" in url for url in cached["urls"])
        assert any("/static/kokuen.css?v=21" in url for url in cached["urls"])
        assert sum("/static/js/" in url for url in cached["urls"]) >= 20
        page.screenshot(path=str(OUTPUT / "pwa-plan-online-mobile.png"), full_page=True)

        offline["active"] = True
        context.set_offline(True)
        page.goto(f"{BASE}/?app=andromeda", wait_until="domcontentloaded")
        try:
            page.wait_for_function(
                "() => !document.body.classList.contains('preboot')", timeout=10_000
            )
        except Exception:
            diagnostic = page.evaluate(
                """async () => ({
                  url: location.href,
                  bodyClass: document.body.className,
                  scripts: [...document.scripts].map(script => script.src).filter(Boolean),
                  cacheNames: await caches.keys(),
                  appModule: await (async () => {
                    const match = await caches.match('/static/js/app.js?v=303');
                    return match ? { status: match.status, size: (await match.clone().text()).length } : null;
                  })(),
                  appModuleKeys: await (async () => {
                    const cache = await caches.open('alles-v258');
                    return (await cache.keys())
                      .map(request => request.url)
                      .filter(url => url.includes('/static/js/app.js'));
                  })(),
                })"""
            )
            page.screenshot(path=str(OUTPUT / "pwa-offline-boot-failure.png"), full_page=True)
            print(
                {
                    "offline_boot": diagnostic,
                    "browser_errors": errors,
                    "failed_requests": failed_requests,
                }
            )
            raise
        _assert_shell(page, "andromeda")
        expect(page.locator("#andromeda-view")).to_be_visible()
        expect(page.locator("#sync-indicator")).to_be_attached()
        page.screenshot(path=str(OUTPUT / "pwa-andromeda-offline-mobile.png"), full_page=True)

        context.set_offline(False)
        offline["active"] = False
        page.goto(f"{BASE}/?app=aide", wait_until="networkidle")
        _assert_shell(page, "aide")
        expect(page.locator("#chat")).to_be_visible()
        page.screenshot(path=str(OUTPUT / "pwa-aide-reconnected-mobile.png"), full_page=True)

        browser.close()

    if errors:
        raise AssertionError("PWA console errors:\n" + "\n".join(errors))
    print(f"PWA install/offline/reconnect gate passed; captures: {OUTPUT}")


if __name__ == "__main__":
    run()

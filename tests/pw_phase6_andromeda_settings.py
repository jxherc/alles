"""Rendered Phase 6 gate for Andromeda's complete settings surface."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
BASE = f"http://127.0.0.1:{PORT}"


def run() -> None:
    browser_errors: list[str] = []
    screenshot_dir = os.environ.get("SCREENSHOT_DIR", "").strip()
    if screenshot_dir:
        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    managed_actions: list[str] = []
    settings_patches: list[dict] = []
    service = {
        "support_verified": True,
        "available": True,
        "installed": False,
        "owned": True,
        "running": False,
        "healthy": False,
        "bind": "127.0.0.1:8888",
        "version": "2026.7.12-c19d86faa",
        "license": "AGPL-3.0",
        "data_kept": True,
    }
    fail_status = False

    def route_settings(route):
        if route.request.method == "PATCH":
            body = route.request.post_data_json
            settings_patches.append(body)
        else:
            body = {}
        payload = {
            "search_provider": "searxng",
            "search_fallback": "brave",
            "search_fallback_chain": ["brave"],
            "search_result_count": 10,
            "searxng_url": "http://127.0.0.1:8888",
            "brave_api_key_configured": True,
            "andromeda_normal_results": True,
            "andromeda_overview": True,
            "andromeda_model_band": "standard",
            **body,
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def route_managed(route):
        nonlocal fail_status
        path = urlparse(route.request.url).path
        if route.request.method == "GET":
            if fail_status:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": "managed status unavailable"}),
                )
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(service))
            return
        action = path.rsplit("/", 1)[-1]
        managed_actions.append(action)
        if action == "install":
            service.update(installed=True, running=True, healthy=True)
        elif action == "stop":
            service.update(running=False, healthy=False)
        elif action in {"start", "restart"}:
            service.update(running=True, healthy=True)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(service))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label in (
            (1440, 1000, "desktop"),
            (390, 844, "mobile"),
            (195, 422, "zoom200"),
        ):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(5_000)
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    browser_errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.route("**/api/settings", route_settings)
            page.route("**/api/system/searxng**", route_managed)
            page.route("**/api/system/services/searxng/**", route_managed)
            page.goto(BASE, wait_until="networkidle")
            page.evaluate("window._navigateTo('andromeda')")
            page.wait_for_selector("#andromeda-view:visible")
            page.locator("#andromeda-idle-settings").click()
            panel = page.locator("#andromeda-settings-panel")
            panel.wait_for(state="visible")

            required = (
                "#andromeda-provider",
                "#andromeda-primary-provider",
                "#andromeda-fallback-provider",
                "#andromeda-result-count",
                "#andromeda-searxng-status",
                "#andromeda-results-toggle",
                "#andromeda-overview-toggle",
                "#andromeda-band",
                "#andromeda-exact-model",
                "#andromeda-saved-list",
            )
            for selector in required:
                assert page.locator(selector).count() == 1, f"{label}: missing {selector}"
            assert "searxng → brave" in page.locator("#andromeda-provider-order").inner_text()
            guide = page.locator(".andromeda-strength-guide").inner_text().lower()
            for phrase in (
                "fastest, shortest answer, least checking",
                "balanced speed and checking",
                "slower, longer answer, more checking",
                "query and available model",
            ):
                assert phrase in guide, (label, guide)
            assert page.locator(".andromeda-strength-guide").evaluate(
                "el => Number.parseFloat(getComputedStyle(el).paddingTop) >= 8"
            ), f"{label}: overview guide needs breathing room above its first line"
            assert page.locator("#andromeda-search-settings-status").is_hidden(), (
                f"{label}: an empty save status must not reserve a blank row"
            )

            box = panel.bounding_box()
            assert box is not None
            assert box["x"] >= 0 and box["y"] >= 0, (label, box)
            assert box["x"] + box["width"] <= width + 1, (label, box, width)
            assert box["y"] + box["height"] <= height + 1, (label, box, height)
            assert panel.evaluate("el => el.scrollHeight >= el.clientHeight")
            assert page.locator("#andromeda-settings-panel select:visible").count() == 0
            assert (
                page.locator("#andromeda-settings-panel input[type=checkbox]:visible").count() == 0
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert panel.evaluate("el => el.scrollWidth <= el.clientWidth"), (
                label,
                panel.evaluate(
                    "el => ({scrollWidth: el.scrollWidth, clientWidth: el.clientWidth})"
                ),
            )
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / f"andromeda-settings-{label}.png"),
                    full_page=True,
                )

            if label == "desktop":
                page.wait_for_selector('[data-searxng-action="install"]')
                page.locator('[data-searxng-action="install"]').click()
                page.wait_for_function(
                    "() => document.querySelector('#andromeda-searxng-status')?.textContent === 'healthy'"
                )
                assert managed_actions[-1] == "install"
                labels = page.locator("#andromeda-searxng-actions button").all_inner_texts()
                assert labels == [
                    "stop",
                    "restart",
                    "test search",
                    "safe update",
                    "rollback",
                    "uninstall · keep data",
                ], labels
                page.locator("#andromeda-primary-provider").click()
                page.locator(".custom-dropdown-option", has_text="duckduckgo").last.click()
                page.locator("#andromeda-fallback-provider").click()
                page.locator(".custom-dropdown-option", has_text="duckduckgo").last.click()
                page.wait_for_function(
                    "() => document.querySelector('#andromeda-provider-order')?.textContent === 'duckduckgo'"
                )
                if screenshot_dir:
                    panel.screenshot(
                        path=str(Path(screenshot_dir) / "andromeda-settings-single-provider.png")
                    )
                page.locator("#andromeda-primary-provider").click()
                page.locator(".custom-dropdown-option", has_text="brave").last.click()
                page.wait_for_function(
                    "() => document.querySelector('#andromeda-provider-order')?.textContent.startsWith('brave')"
                )
                assert settings_patches[-1]["search_provider"] == "brave"
                fail_status = True
                page.locator("#andromeda-searxng-refresh").click()
                page.wait_for_function(
                    "() => document.querySelector('#andromeda-searxng-meta')?.textContent.includes('External search providers')"
                )
                browser_errors[:] = [
                    message
                    for message in browser_errors
                    if message
                    != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                ]
                fail_status = False

            page.locator("#andromeda-settings-close").focus()
            page.keyboard.press("Escape")
            assert panel.is_hidden()
            context.close()
        browser.close()

    if browser_errors:
        raise AssertionError("Andromeda settings browser errors:\n" + "\n".join(browser_errors))
    print("Andromeda full settings and managed SearXNG browser gate passed")


if __name__ == "__main__":
    run()

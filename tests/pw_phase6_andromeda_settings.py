"""Rendered Phase 6 gate for Andromeda's section of the one settings screen."""

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
    fail_next_settings_patch = False
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
        nonlocal fail_next_settings_patch
        if route.request.method == "PATCH":
            body = route.request.post_data_json
            settings_patches.append(body)
            if fail_next_settings_patch:
                fail_next_settings_patch = False
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": "settings write failed"}),
                )
                return
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
            "context_limit": 57,
            "language": "en",
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
            pane = page.locator("#s-pane-andromeda.active")
            pane.wait_for(state="visible")
            content = page.locator("#settings-modal .s-content")
            assert page.locator("#andromeda-settings-panel").count() == 0

            required = (
                "#s-andromeda-primary",
                "#s-andromeda-fallback",
                "#s-andromeda-count",
                "#s-andromeda-searxng-status",
                "#s-andromeda-results",
                "#s-andromeda-overview",
                "#s-andromeda-band",
                "#s-andromeda-answer-model",
            )
            for selector in required:
                assert page.locator(selector).count() == 1, f"{label}: missing {selector}"
            for selector in (
                "#andromeda-provider",
                "#andromeda-exact-model",
                "#andromeda-saved-list",
            ):
                assert page.locator(selector).count() == 0, (
                    f"{label}: {selector} is back on the page"
                )
            for name in (
                "normal results",
                "ai overview",
                "ask before each remote search",
                "independent fact-check",
            ):
                switch = pane.get_by_role("switch", name=name, exact=True)
                assert switch.count() == 1, (label, name)
                box = switch.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, (label, name, box)
            assert page.locator("#s-andromeda-primary").get_attribute("data-value") == "searxng"
            assert page.locator("#s-andromeda-fallback").get_attribute("data-value") == "brave"
            guide = pane.inner_text().lower()
            for phrase in (
                "fastest, shortest answer, least checking",
                "balanced speed and checking",
                "slower, longer answer, more checking",
                "query and available model",
            ):
                assert phrase in guide, (label, guide)

            assert page.locator("#s-pane-andromeda select:visible").count() == 0
            assert page.locator("#s-pane-andromeda input[type=checkbox]:visible").count() == 0
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert content.evaluate("el => el.scrollWidth <= el.clientWidth"), (
                label,
                content.evaluate(
                    """el => ({
                      scrollWidth: el.scrollWidth,
                      clientWidth: el.clientWidth,
                      overflow: [...el.querySelectorAll('*')].map(node => ({
                        tag: node.tagName.toLowerCase(), id: node.id,
                        className: typeof node.className === 'string' ? node.className : '',
                        scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
                        left: node.getBoundingClientRect().left,
                        right: node.getBoundingClientRect().right,
                      })).filter(row => row.scrollWidth > row.clientWidth || row.right > innerWidth),
                    })"""
                ),
            )
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / f"andromeda-settings-{label}.png"),
                    full_page=True,
                )

            if label == "desktop":
                results_switch = pane.get_by_role("switch", name="normal results", exact=True)
                assert results_switch.get_attribute("aria-checked") == "true"
                fail_next_settings_patch = True
                results_switch.click()
                page.wait_for_function(
                    "() => document.querySelector('#s-pane-andromeda .settings-save-state')?.textContent.includes('Try the control again')"
                )
                assert results_switch.get_attribute("aria-checked") == "true"
                assert results_switch.get_attribute("aria-busy") is None
                assert results_switch.is_enabled()
                browser_errors[:] = [
                    message
                    for message in browser_errors
                    if message
                    != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                ]
                results_switch.press("Enter")
                page.wait_for_function(
                    """() => {
                      const node = document.querySelector('#s-andromeda-results');
                      return node?.getAttribute('aria-checked') === 'false'
                        && node.getAttribute('aria-busy') !== 'true'
                        && !node.disabled;
                    }"""
                )
                assert settings_patches[-1]["andromeda_normal_results"] is False
                assert results_switch.get_attribute("aria-busy") is None
                assert results_switch.is_enabled()

                page.wait_for_selector('[data-searxng-action="install"]')
                page.locator('[data-searxng-action="install"]').click()
                page.wait_for_function(
                    "() => document.querySelector('#s-andromeda-searxng-status')?.textContent === 'healthy'"
                )
                assert managed_actions[-1] == "install"
                labels = page.locator("#s-andromeda-searxng-actions button").all_inner_texts()
                assert labels == [
                    "stop",
                    "restart",
                    "test search",
                    "safe update",
                    "rollback",
                    "uninstall · keep data",
                ], labels
                page.locator("#s-andromeda-primary").click()
                page.locator(".custom-dropdown-option", has_text="free search").last.click()
                page.wait_for_function(
                    "() => document.querySelector('#s-andromeda-primary')?.dataset.value === 'duckduckgo'"
                )
                page.locator("#s-andromeda-fallback").click()
                page.locator(".custom-dropdown-option", has_text="free search").last.click()
                # a fallback equal to the primary engine is saved as none
                page.wait_for_function(
                    "() => document.querySelector('#s-andromeda-fallback')?.dataset.value === 'none'"
                )
                assert settings_patches[-1]["search_provider"] == "duckduckgo"
                assert settings_patches[-1]["search_fallback"] == "none"
                if screenshot_dir:
                    pane.screenshot(
                        path=str(Path(screenshot_dir) / "andromeda-settings-single-provider.png")
                    )
                page.locator("#s-andromeda-primary").click()
                page.locator(".custom-dropdown-option", has_text="Brave").last.click()
                page.wait_for_function(
                    "() => document.querySelector('#s-andromeda-primary')?.dataset.value === 'brave'"
                )
                assert settings_patches[-1]["search_provider"] == "brave"
                fail_status = True
                page.locator("#s-andromeda-searxng-refresh").click()
                page.wait_for_function(
                    "() => document.querySelector('#s-andromeda-searxng-meta')?.textContent.includes('External search providers')"
                )
                browser_errors[:] = [
                    message
                    for message in browser_errors
                    if message
                    != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                ]
                fail_status = False

            page.locator("#settings-modal-close").focus()
            page.keyboard.press("Escape")
            assert page.locator("#settings-modal").is_hidden()
            context.close()
        browser.close()

    if browser_errors:
        raise AssertionError("Andromeda settings browser errors:\n" + "\n".join(browser_errors))
    print("Andromeda full settings and managed SearXNG browser gate passed")


if __name__ == "__main__":
    run()

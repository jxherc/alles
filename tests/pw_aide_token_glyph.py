"""Rendered regression for the Aide latest-response token mark.

Run against an isolated Alles server on port 8893. The browser intercepts API
requests, so no configured model or owner data is used.
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8893")
AIDE = f"http://aide.localhost:{PORT}"
EVIDENCE = Path(os.environ.get("ALLES_TEST_EVIDENCE", "/tmp/alles-aide-token-glyph"))


def _json(route, value, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(value))


def _route_api(state):
    def handler(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method

        if path == "/api/auth/me":
            return _json(route, {"authenticated": True, "auth_enabled": False, "username": "test"})
        if path in {"/api/settings", "/api/appearance"}:
            return _json(
                route,
                {
                    "base_domain": "localhost",
                    "setup_done": True,
                    "language": "en",
                    "theme": "dark",
                },
            )
        if path == "/api/models":
            return _json(
                route,
                [
                    {
                        "id": "token-test",
                        "name": "local test",
                        "provider": "ollama",
                        "base_url": "http://127.0.0.1:11434",
                        "models": ["token-test-model"],
                        "image_models": [],
                        "unavailable_models": [],
                    }
                ],
            )
        if path == "/api/models/roles":
            return _json(
                route,
                {
                    "aide_chat": {
                        "status": "ready",
                        "effective": {
                            "endpoint_id": "token-test",
                            "model": "token-test-model",
                        },
                    }
                },
            )
        if path == "/api/sessions" and method == "GET":
            return _json(route, {"today": state["sessions"], "yesterday": [], "earlier": []})
        if path == "/api/sessions" and method == "POST":
            session = {
                "id": "token-session",
                "name": "token glyph check",
                "model": "token-test-model",
                "endpoint_id": "token-test",
                "incognito": False,
                "starred": False,
            }
            state["sessions"] = [session]
            return _json(route, session)
        if path == "/api/chat" and method == "POST":
            state["chat_posts"] += 1
            body = (
                'data: {"delta":"rendered response"}\n\n'
                'data: {"done":true,"usage":{"prompt_tokens":7,"completion_tokens":5}}\n\n'
                "data: [DONE]\n\n"
            )
            return route.fulfill(status=200, content_type="text/event-stream", body=body)
        if path.endswith("/auto-name"):
            return _json(route, {"name": "token glyph check"})
        if path.endswith("/history"):
            return _json(route, {"session": state["sessions"][0], "messages": []})
        if path in {"/api/projects", "/api/personas", "/api/cookbook"}:
            return _json(route, [])
        if path == "/api/system/build":
            return _json(route, {"version": "test"})
        return _json(route, {})

    return handler


def _visible(page, selector):
    return page.locator(selector).evaluate(
        "el => !el.hidden && getComputedStyle(el).display !== 'none' && !!el.getClientRects().length"
    )


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state = {"sessions": [], "chat_posts": 0}
    results = {}
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            service_workers="block",
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.route("**/api/**", _route_api(state))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )

        page.goto(AIDE, wait_until="domcontentloaded")
        page.wait_for_selector("#composer-ta", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#aide-model-choice-label')?.textContent.includes('token test model')"
        )
        page.fill("#composer-ta", "show the token mark")
        page.press("#composer-ta", "Enter")
        page.wait_for_function(
            "document.querySelector('#session-token-count-value')?.textContent === '12 tok'"
        )

        counter = page.locator("#session-token-count")
        mark = page.locator(".session-token-mark")
        results["one_chat_request"] = state["chat_posts"] == 1
        results["counter_visible"] = _visible(page, "#session-token-count")
        results["bare_fragment_mark"] = mark.count() == 1 and mark.locator("path").count() == 1
        results["accessible_usage_label"] = (
            counter.get_attribute("role") == "status"
            and counter.get_attribute("aria-live") == "polite"
            and counter.get_attribute("aria-label") == "12 tokens used in the latest response"
        )
        styles = mark.evaluate(
            "el => ({width: getComputedStyle(el).width, height: getComputedStyle(el).height, background: getComputedStyle(el).backgroundColor})"
        )
        results["mark_size_and_surface"] = (
            styles["width"] == "14px"
            and styles["height"] == "14px"
            and styles["background"] == "rgba(0, 0, 0, 0)"
        )
        page.screenshot(path=str(EVIDENCE / "token-dark-desktop.png"), full_page=True)

        page.evaluate(
            """() => {
                const root = document.documentElement;
                root.dataset.theme = 'light';
                root.style.setProperty('--bg', '#f5f4f1');
                root.style.setProperty('--text', '#111111');
                root.style.setProperty('--panel', '#efede9');
                root.style.setProperty('--faint', '#d4d2ce');
                root.style.setProperty('--muted', '#625f5a');
            }"""
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(100)
        if "sidebar-hidden" not in (page.locator("body").get_attribute("class") or ""):
            page.keyboard.press("Control+b")
            page.wait_for_function("document.body.classList.contains('sidebar-hidden')")
        token_box = counter.bounding_box()
        action_box = page.locator("#aide-work-panel-toggle").bounding_box()
        results["phone_visible"] = _visible(page, "#session-token-count")
        results["phone_no_action_overlap"] = bool(
            token_box
            and action_box
            and token_box["x"] + token_box["width"] <= action_box["x"] + 0.5
        )
        results["phone_no_page_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        results["light_theme_rendered"] = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() === '#f5f4f1'"
        )
        page.screenshot(path=str(EVIDENCE / "token-light-phone.png"), full_page=True)
        browser.close()

    results["zero_console_errors"] = not errors
    for name, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    if errors:
        print("console_errors:", errors[:8])
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

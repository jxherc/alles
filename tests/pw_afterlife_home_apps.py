"""Browser gate for the Afterlife Home and Apps surfaces."""

import json
import os

from playwright.sync_api import Route, sync_playwright

PORT = os.environ.get("PORT", "8931")
BASE = f"http://localhost:{PORT}"


TODAY = {
    "date": "2026-07-13",
    "partial_sources": [],
    "sections": {
        "needs_you": [
            {
                "title": "review the budget",
                "summary": "one category is over plan",
                "state": "uncertain",
            },
            {
                "title": "reply to mia",
                "summary": "the message has waited since yesterday",
                "state": "ready",
            },
        ],
        "today": {
            "events": [
                {"time": "09:30", "title": "standup"},
                {"time": "14:00", "title": "design review"},
            ],
            "tasks": {
                "open_count": 3,
                "overdue": [{"title": "file taxes"}],
                "due_today": [{"title": "finish the home page"}],
            },
            "reminders": [],
            "renewing": [],
            "day_events": [],
            "habits": [{"name": "stretch"}],
        },
        "in_progress": [],
        "briefs": [
            {
                "summary": "*No urgent mail.* **The backup finished this morning.** "
                + ("More background detail. " * 20)
            }
        ],
        "shortcuts": [],
    },
}


def mock_home(route: Route) -> None:
    if "/api/today/preferences" in route.request.url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps({}))
    elif "/api/today" in route.request.url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(TODAY))
    else:
        route.continue_()


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.route("**/api/today**", mock_home)
            page.goto(BASE, wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            page.wait_for_selector("#today-greeting")

            assert page.locator("#today-view").is_visible()
            assert page.locator("#today-greeting").is_visible()
            assert "preboot" not in (page.locator("body").get_attribute("class") or "")
            assert page.locator("#today-settings").count() == 1
            assert page.locator("#today-settings").inner_text() == "settings"
            assert page.locator("#today-settings").get_attribute("aria-haspopup") is None
            assert page.locator(".today-shortcut-section h2").inner_text() == "pinned apps"
            assert page.locator(".today-shortcut-section header > span").count() == 0
            assert page.locator(".today-shortcut").count() == 3
            assert page.locator(".today-shortcut b").all_inner_texts() == [
                "plan",
                "docs",
                "files",
            ]
            page.locator("#today-settings").click()
            page.wait_for_selector("#settings-modal:visible")
            page.locator("#settings-modal-close").click()
            assert not page.locator("#settings-modal").is_visible()
            assert (
                page.locator("#today-capture-input").get_attribute("placeholder")
                == "capture something…"
            )
            if label == "desktop":
                page.evaluate(
                    """() => {
                      const originalFetch = window.fetch.bind(window);
                      window.__captureCalls = 0;
                      window.__failNextHomeLoad = false;
                      window.fetch = (input, init = {}) => {
                        const url = String(input);
                        if (url === '/api/tasks' && init.method === 'POST') {
                          window.__captureCalls += 1;
                          return new Promise(resolve => {
                            window.__releaseCapture = () => resolve(new Response(
                              JSON.stringify({id: 'capture-fixture'}),
                              {status: 200, headers: {'content-type': 'application/json'}},
                            ));
                          });
                        }
                        if (url.startsWith('/api/today?') && window.__failNextHomeLoad) {
                          window.__failNextHomeLoad = false;
                          return Promise.resolve(new Response('{}', {status: 503}));
                        }
                        return originalFetch(input, init);
                      };
                    }"""
                )
                capture = page.locator("#today-capture-input")
                capture.fill("one task only")
                capture.press("Enter")
                page.wait_for_function("window.__captureCalls === 1")
                page.evaluate("document.getElementById('today-capture').requestSubmit()")
                assert page.evaluate("window.__captureCalls") == 1
                assert capture.is_disabled()
                assert page.locator("#today-capture-mode").is_disabled()
                assert page.locator('.today-capture [type="submit"]').is_disabled()
                page.evaluate("window.__failNextHomeLoad = true; window.__releaseCapture();")
                page.wait_for_selector("#today-retry", state="visible")
                page.wait_for_timeout(1_800)
                assert page.locator("#today-retry").is_visible()
                page.locator("#today-retry").click()
                page.wait_for_selector("#today-status", state="hidden")
            assert page.locator(".today-row").count() >= 5
            brief = page.locator(".today-brief p")
            brief_text = brief.inner_text()
            assert "*" not in brief_text
            assert len(brief_text) <= 181
            assert brief.evaluate("el => el.getBoundingClientRect().height < 56")
            assert (
                page.locator("#space-rail").evaluate("el => getComputedStyle(el).display") == "none"
            )
            home_frame = page.locator(".today-topbar").bounding_box()
            assert home_frame is not None
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            first_clock = page.locator("#today-clock").inner_text()
            page.wait_for_timeout(1_100)
            assert page.locator("#today-clock").inner_text() != first_clock
            page.screenshot(path=f"/tmp/alles-home-{label}.png", full_page=True)
            page.locator(".today-shortcut-section").scroll_into_view_if_needed()
            page.screenshot(path=f"/tmp/alles-home-pinned-apps-{label}.png")

            page.locator('.today-shortcut[data-view="plan"]').click()
            page.wait_for_selector("#plan-view:visible")
            assert (
                page.locator(
                    '[data-specialist-app="plan"] [data-group-section="overview"]'
                ).get_attribute("aria-selected")
                == "true"
            )
            page.locator("#plan-view [data-specialist-home]").click()
            page.wait_for_url(f"http://localhost:{PORT}/")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("#today-view:visible")

            page.locator('[data-today-destination="apps"]').click()
            page.wait_for_selector("#app-drawer:not([hidden])")
            assert page.locator(".app-drawer-group").count() == 3
            assert page.locator(".app-drawer-item").count() == 9
            assert page.locator(".app-drawer-group h3").all_inner_texts() == [
                "everyday",
                "personal",
                "manage",
            ]
            assert page.locator(".app-drawer-item b").all_inner_texts() == [
                "plan",
                "inbox",
                "docs",
                "files",
                "library",
                "health",
                "finance",
                "vault",
                "server",
            ]
            assert (
                page.locator("#app-drawer").evaluate(
                    "el => Math.round(el.getBoundingClientRect().width)"
                )
                == width
            )
            assert (
                page.locator("#app-drawer").evaluate("el => getComputedStyle(el).position")
                == "fixed"
            )
            apps_frame = page.locator(".app-drawer-head").bounding_box()
            assert apps_frame is not None
            assert abs(home_frame["x"] - apps_frame["x"]) <= 1
            assert (
                abs(
                    (home_frame["x"] + home_frame["width"])
                    - (apps_frame["x"] + apps_frame["width"])
                )
                <= 1
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )

            page.screenshot(path=f"/tmp/alles-apps-{label}.png", full_page=True)
            page.locator("#app-drawer-close").click()
            assert page.locator("#app-drawer").is_hidden()
            assert page.locator("#today-view").is_visible()

            page.locator('[data-today-destination="apps"]').click()
            page.locator('.app-drawer-item[data-view="plan"]').click()
            page.wait_for_selector("#plan-view:visible")
            assert page.locator("#app-drawer").is_hidden()
            assert (
                page.locator("#space-rail").evaluate("el => getComputedStyle(el).display") == "none"
            )
            page.locator("#plan-view [data-specialist-home]").click()
            page.wait_for_url(f"http://localhost:{PORT}/")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("#today-view:visible")
            context.close()

        # On one-host installs, activate the destination before removing the
        # full-screen Apps cover. This prevents even one exposed Home frame.
        single_context = browser.new_context(
            viewport={"width": 1280, "height": 800}, service_workers="block"
        )
        single_page = single_context.new_page()
        single_page.route("**/api/today**", mock_home)
        single_page.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        single_page.locator('[data-today-destination="apps"]').click()
        single_page.wait_for_selector("#app-drawer:not([hidden])")
        single_page.evaluate(
            """() => {
                window.__appsTransitionOrder = [];
                const drawer = document.getElementById('app-drawer');
                const docs = document.getElementById('wiki-view');
                const observer = new MutationObserver(records => {
                    for (const record of records) {
                        if (record.target === docs && record.attributeName === 'style') {
                            window.__appsTransitionOrder.push('docs');
                        }
                        if (record.target === drawer && record.attributeName === 'hidden') {
                            window.__appsTransitionOrder.push('drawer');
                        }
                    }
                });
                observer.observe(drawer, {attributes: true});
                observer.observe(docs, {attributes: true});
            }"""
        )
        single_page.locator('.app-drawer-item[data-view="wiki"]').click()
        single_page.wait_for_selector("#wiki-view:visible")
        single_page.wait_for_selector("#app-drawer", state="hidden")
        transition_order = single_page.evaluate("window.__appsTransitionOrder")
        assert transition_order.index("docs") < transition_order.index("drawer"), transition_order
        single_context.close()

        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("home/apps browser gate passed")


if __name__ == "__main__":
    run()

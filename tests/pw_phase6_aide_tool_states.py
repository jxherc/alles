"""Live loading, empty/ready, and error-state gate for Aide's four tool pages."""

import os

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
BASE = f"http://127.0.0.1:{PORT}"
TOOLS = {
    "scheduled": "aide-scheduled-view",
    "brain": "brain-view",
    "skills": "skills-view",
    "aide-reminders": "reminders-view",
}


def _page(browser):
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.goto(BASE, wait_until="networkidle")
    page.evaluate("window._navigateTo('chat')")
    return context, page


def run() -> None:
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for view, root_id in TOOLS.items():
            context, page = _page(browser)
            pending_routes = []
            gate = {"held": True}

            def hold_api(route):
                if gate["held"]:
                    pending_routes.append(route)
                else:
                    route.continue_()

            page.route("**/api/**", hold_api)
            page.evaluate(
                "view => { window.__aideToolProbeNavigation = window._navigateTo(view); }",
                view,
            )
            root = page.locator(f"#{root_id}")
            try:
                root.wait_for(state="visible", timeout=5_000)
                loading = root.locator(':scope > .specialist-state[data-state="loading"]')
                loading.wait_for(state="visible", timeout=5_000)
                assert root.get_attribute("aria-busy") == "true"
                page.wait_for_timeout(100)
                assert pending_routes, "tool loading did not reach a controlled API request"
                gate["held"] = False
                for pending_route in pending_routes:
                    pending_route.continue_()
                page.evaluate("window.__aideToolProbeNavigation")
                page.evaluate("delete window.__aideToolProbeNavigation")
                page.wait_for_function(
                    "id => document.querySelector('#' + id)?.getAttribute('aria-busy') === 'false'",
                    arg=root_id,
                    timeout=8_000,
                )
                page.unroute("**/api/**", hold_api)
                assert len(root.inner_text().strip()) >= 8
            except Exception as exc:  # noqa: BLE001 - aggregate all tools
                failures.append(f"{view}: loading/ready state failed ({exc})")
            context.close()

            context, page = _page(browser)
            page.route(
                "**/api/**",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"phase 6 forced failure"}',
                ),
            )
            page.evaluate("view => window._navigateTo(view)", view)
            root = page.locator(f"#{root_id}")
            try:
                root.wait_for(state="visible", timeout=5_000)
                state = root.locator(':scope > .specialist-state[data-state="error"]')
                state.wait_for(state="visible", timeout=5_000)
                assert state.locator("button").is_enabled()
            except Exception as exc:  # noqa: BLE001 - aggregate all tools
                failures.append(f"{view}: error/retry state failed ({exc})")
            context.close()

        context, page = _page(browser)
        try:
            page.evaluate(
                """() => {
                  const NativeWebSocket = window.WebSocket;
                  window.__aideTerminalSockets = [];
                  window.WebSocket = class TrackingWebSocket extends NativeWebSocket {
                    constructor(...args) {
                      super(...args);
                      window.__aideTerminalSockets.push(this);
                    }
                  };
                }"""
            )
            page.locator("#aide-work-panel-toggle").click()
            page.locator('[data-aide-tool="terminal"]').click()
            page.locator("#aide-terminal-mount .xterm").wait_for(state="visible")
            page.wait_for_function("window.__aideTerminalSockets.length === 1")
            page.wait_for_function("window.__aideTerminalSockets[0]?.readyState === 1")
            page.evaluate(
                """window._syncAideNewTaskContext({
                  id: 'terminal-context-two',
                  project_id: '',
                  environment: {kind: 'default'}
                })"""
            )
            assert page.locator("#aide-task-tools").is_visible(), (
                "changing task context did not return to task tools"
            )
            assert page.locator("#aide-terminal").evaluate("element => element.hidden"), (
                "changing task context left the prior terminal visible"
            )
            page.wait_for_function("window.__aideTerminalSockets[0]?.readyState >= 2")
            page.locator('[data-aide-tool="terminal"]').click()
            page.wait_for_function("window.__aideTerminalSockets.length === 2")
            page.wait_for_function("window.__aideTerminalSockets[1]?.readyState === 1")
            page.locator("#aide-work-panel-close").click()
            assert page.locator("#aide-terminal").evaluate("element => element.hidden"), (
                "closing the work panel left the terminal subview selected"
            )
            page.wait_for_function("window.__aideTerminalSockets[1]?.readyState >= 2")
            page.locator("#aide-work-panel-toggle").click()
            assert page.locator("#aide-task-tools").is_visible(), (
                "reopening the work panel did not return to task tools"
            )
            assert page.locator("#aide-terminal").evaluate("element => element.hidden"), (
                "reopening the work panel exposed the prior terminal"
            )
            page.locator('[data-aide-tool="terminal"]').click()
            page.wait_for_function("window.__aideTerminalSockets.length === 3")
            page.wait_for_function("window.__aideTerminalSockets[2]?.readyState === 1")
            page.locator("#aide-work-panel-close").click()
            page.wait_for_function("window.__aideTerminalSockets[2]?.readyState >= 2")
        except Exception as exc:  # noqa: BLE001 - aggregate the terminal gate
            failures.append(f"terminal context/panel reset failed ({exc})")
        context.close()
        browser.close()

    if failures:
        raise AssertionError("Aide tool state regressions:\n" + "\n".join(failures))
    print(
        "all four Aide tools passed loading, ready/empty, and error-state gates; "
        "task-context changes and panel closes reset terminal connections"
    )


if __name__ == "__main__":
    run()

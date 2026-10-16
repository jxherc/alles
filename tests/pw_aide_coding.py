"""Visual and interaction gate for the DSH coding handoff."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]

from _dsh_contract_stub import DshContractStub  # noqa: E402
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
stub = DshContractStub()
events = {"console": [], "page_errors": [], "failed_requests": [], "external": []}
scenarios = []


def context_for(browser, *, width, theme):
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 390 else 844},
        has_touch=width == 390,
        locale="en-US",
        timezone_id="UTC",
        reduced_motion="reduce",
        service_workers="block",
    )
    assert context.request.put(base + "/api/appearance", data=from_legacy(theme, None)).ok

    def boundary(route):
        target = urlsplit(route.request.url)
        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            events["external"].append(route.request.url)
            return route.abort()
        return route.continue_()

    context.route("**/*", boundary)
    return context


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            desktop = context_for(browser, width=1440, theme="dark")
            assert desktop.request.post(base + "/api/setup/dismiss").ok
            page = desktop.new_page()
            page.set_default_timeout(15_000)
            page.on(
                "console",
                lambda message: (
                    events["console"].append(message.text) if message.type == "error" else None
                ),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda request: events["failed_requests"].append(
                    {"url": request.url, "failure": request.failure}
                ),
            )
            page.goto(base + "/?view=chat", wait_until="networkidle")
            coding = page.locator("#aide-mode-coding")
            assert coding.bounding_box()["height"] >= 44
            coding.focus()
            coding.press("Enter")
            expect(page.locator("#aide-coding-workspace")).to_be_visible()
            expect(page.locator("#aide-coding-pair")).to_be_hidden()
            expect(page.locator("#aide-coding-submit")).to_be_disabled()
            page.locator("#aide-coding-connection-toggle").click()
            expect(page.locator("#aide-coding-pair")).to_be_visible()
            page.screenshot(path=str(out / "aide-coding-pairing-dark.png"))

            page.get_by_label("DSH bridge on this Mac", exact=True).fill(stub.base_url)
            page.get_by_label("8-digit code shown by DSH", exact=True).fill("12345678")
            page.locator("#aide-coding-pair").get_by_role(
                "button", name="connect DSH", exact=True
            ).click()
            expect(page.locator("#aide-coding-status")).to_contain_text("DSH connected")
            page.locator("#aide-coding-connection-back").click()
            expect(page.locator("#aide-coding-project-title")).to_have_text("Alles · local stub")
            page.locator("#aide-coding-project").press("Enter")
            expect(page.locator("#aide-coding-workspace-menu")).to_be_visible()
            page.keyboard.press("End")
            page.keyboard.press("Escape")
            expect(page.locator("#aide-coding-project")).to_be_focused()
            prompt = (
                "Fix the lifecycle edge case, run focused tests, and report the verified result."
            )
            page.get_by_label("instruction", exact=True).fill(prompt)
            page.evaluate("""() => {
              const actualFetch = window.fetch;
              window.__codingRequestIds = [];
              let losePost = true, loseRead = true;
              window.fetch = async (input, init = {}) => {
                const path = String(input);
                if (path === '/api/aide/coding/runs' && init.method === 'POST') {
                  window.__codingRequestIds.push(JSON.parse(init.body).request_id);
                  const response = await actualFetch(input, init);
                  if (losePost) { losePost = false; throw new TypeError('synthetic response lost'); }
                  return response;
                }
                if (loseRead && /^\\/api\\/aide\\/coding\\/runs\\/[^/]+$/.test(path)) {
                  loseRead = false; throw new TypeError('synthetic reconciliation unavailable');
                }
                return actualFetch(input, init);
              };
              const form = document.getElementById('aide-coding-start');
              form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
              form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            }""")
            expect(page.locator("#aide-coding-error")).to_contain_text(
                "Retry this unchanged instruction"
            )
            assert len(stub.sessions) == 1
            page.get_by_role("button", name="start in DSH", exact=True).click()
            run = page.locator(".aide-coding-run").first
            expect(run).to_contain_text("request accepted")
            ids = page.evaluate("window.__codingRequestIds")
            assert len(ids) == 2 and ids[0] == ids[1], ids
            assert len(stub.sessions) == 1
            expect(run).to_contain_text(prompt)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=str(out / "aide-coding-running-dark.png"))

            run_id = next(iter(stub.sessions))
            stub.complete(run_id)
            run.get_by_role("button", name="refresh", exact=True).click()
            expect(page.locator(".aide-coding-run").first).to_contain_text("completed")
            expect(page.locator("#aide-coding-output")).to_contain_text(
                "fixed the synthetic lifecycle test"
            )
            expect(page.locator("#aide-coding-output")).to_contain_text("assert completed")
            page.locator("#aide-coding-record-toggle").click()
            expect(page.locator("#aide-coding-record")).to_be_visible()
            expect(page.locator(".aide-coding-events").first).to_contain_text(
                "saved the coding request"
            )
            page.screenshot(path=str(out / "aide-coding-completed-dark.png"))

            page.get_by_label("follow-up", exact=True).fill(
                "check the second edge case in this session"
            )
            page.get_by_role("button", name="send follow-up", exact=True).click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("request accepted")
            assert len(stub.sessions) == 1
            run.get_by_role("button", name="refresh", exact=True).click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("request accepted")
            stub.complete(run_id)
            run.get_by_role("button", name="refresh", exact=True).click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("completed")
            expect(page.locator("#aide-coding-events")).to_contain_text(
                "check the second edge case"
            )

            # A confirmed blank session can resume, and stop is only final after refresh.
            page.locator("#aide-coding-new").click()
            page.get_by_label("instruction", exact=True).fill(
                "Verify the saved-request recovery path."
            )
            page.get_by_role("button", name="start in DSH", exact=True).click()
            expect(run).to_contain_text("request accepted")
            recovery_id = list(stub.sessions)[-1]
            stub.sessions[recovery_id].update(running=False, blank=True, events=[])
            run.get_by_role("button", name="refresh", exact=True).click()
            expect(run).to_contain_text("ready to send")
            run.get_by_role("button", name="send saved request", exact=True).click()
            expect(run).to_contain_text("request accepted")
            run.get_by_role("button", name="stop", exact=True).click()
            expect(run).to_contain_text("stop requested")
            run.get_by_role("button", name="refresh", exact=True).click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("stopped")

            # The completed run remains selectable and the connection screen is secondary.
            page.locator(f'.acw-run-option[data-run-id="{run_id}"]').click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("completed")
            expect(page.locator("#aide-coding-output")).to_contain_text(
                "fixed the synthetic lifecycle test"
            )
            page.locator("#aide-coding-connection-toggle").click()
            page.locator("#aide-coding-check").click()
            expect(page.locator("#aide-coding-status")).to_contain_text("DSH connected")
            page.keyboard.press("Escape")
            expect(page.locator("#aide-coding-connection-toggle")).to_be_focused()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("completed")
            page.locator("#aide-coding-back").click()
            expect(page.locator("#aide-coding-workspace")).to_be_hidden()
            expect(page.locator("#aide-mode-conversation")).to_have_attribute(
                "aria-pressed", "true"
            )
            scenarios.append(
                {
                    "scenario_id": "aide.coding-handoff.desktop",
                    "status": "passed",
                    "checks": [
                        "explicit synthetic pairing",
                        "contract-faithful DSH start and refresh",
                        "durable receipt details",
                        "blank-session resume and verified stop",
                        "workspace keyboard and connection focus return",
                        "conversation mode exit",
                        "44px tool target and no horizontal overflow",
                    ],
                }
            )
            desktop.close()

            phone = context_for(browser, width=390, theme="light")
            page = phone.new_page()
            page.set_default_timeout(15_000)
            page.on(
                "console",
                lambda message: (
                    events["console"].append(message.text) if message.type == "error" else None
                ),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.goto(base + "/?view=chat", wait_until="networkidle")
            page.locator("#aide-mode-coding").click()
            expect(page.locator(".aide-coding-run").first).to_contain_text("stopped")
            page.locator("#aide-coding-runs-back").click()
            expect(page.locator(".acw-rail")).to_be_visible()
            page.locator(f'.acw-run-option[data-run-id="{run_id}"]').click()
            expect(page.locator("#aide-coding-detail-state")).to_have_text("completed")
            expect(page.locator(".acw-rail")).to_be_hidden()
            panel = page.locator("#aide-coding-workspace")
            assert panel.bounding_box()["width"] <= 390
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=str(out / "aide-coding-completed-phone-light.png"))
            page.locator("#aide-coding-runs-back").click()
            page.locator("#aide-coding-new").click()
            page.get_by_label("instruction", exact=True).fill(
                "Keep this local draft while inspecting connection settings."
            )
            page.locator("#aide-coding-connection-toggle").click()
            page.locator("#aide-coding-disconnect").click()
            expect(page.locator("#aide-coding-pair")).to_be_visible()
            page.locator("#aide-coding-connection-back").click()
            expect(page.get_by_label("instruction", exact=True)).to_have_value(
                "Keep this local draft while inspecting connection settings."
            )
            expect(page.locator("#aide-coding-submit")).to_be_disabled()
            page.locator("#aide-coding-runs-back").click()
            expect(page.locator(".acw-run-option")).to_have_count(2)
            scenarios.append(
                {
                    "scenario_id": "aide.coding-handoff.phone",
                    "status": "passed",
                    "checks": [
                        "390px light theme",
                        "single-pane workspace and explicit back path",
                        "persisted completion receipt",
                        "disconnect preserves runs and unsent draft",
                    ],
                }
            )
            phone.close()
        finally:
            browser.close()
finally:
    stub.close()

assert not events["console"], events
assert not events["page_errors"], events
assert not events["failed_requests"], events
assert not events["external"], events
assert all(path.startswith("/mobile/api/proxy/") for path in stub.paths), stub.paths
(out / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n", encoding="utf-8")
(out / "browser-events.json").write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")

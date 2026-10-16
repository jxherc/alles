"""Delayed coding receipts must preserve later navigation and unsent drafts."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])

DELAY_REPLY = """
const actualFetch = window.fetch;
window.fetch = async (input, init = {}) => {
  const response = await actualFetch(input, init);
  if (init.method === 'POST' && String(input) === window.__holdCodingReply) {
    window.__holdCodingReply = null;
    await new Promise(resolve => { window.__releaseCodingReply = resolve; });
    window.__releaseCodingReply = null;
  }
  return response;
};
"""


def run(browser, width, theme):
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 390 else 844},
        has_touch=width == 390,
        reduced_motion="reduce",
        color_scheme=theme,
        service_workers="block",
    )
    context.add_init_script(DELAY_REPLY)
    events = {"errors": [], "external": [], "failed_requests": []}
    runs = [
        {
            "id": key,
            "prompt": "saved coding run " + key,
            "state": "succeeded",
            "terminal": True,
            "workspace_path": "/synthetic/project",
        }
        for key in ["a", "b"]
    ]

    def boundary(route):
        request, url = route.request, urlsplit(route.request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(request.url)
            return route.abort()
        prefix = "/api/aide/coding/"
        if not url.path.startswith(prefix):
            return route.continue_()
        path = url.path.removeprefix(prefix)
        if path == "status":
            return route.fulfill(json={"configured": True, "available": True})
        if path == "workspaces":
            return route.fulfill(
                json={"items": [{"workspace_id": "synthetic", "title": "test project"}]}
            )
        if path == "runs":
            if request.method == "POST":
                payload = request.post_data_json
                saved = {
                    "id": payload["request_id"],
                    "prompt": payload["prompt"],
                    "state": "succeeded",
                    "terminal": True,
                }
                runs.insert(0, saved)
                return route.fulfill(json=saved)
            return route.fulfill(json={"items": runs})
        if path.endswith("/events"):
            return route.fulfill(json={"items": [], "remote_events": []})
        if path.endswith("/continue"):
            return route.fulfill(json=next(item for item in runs if item["id"] == "a"))
        raise AssertionError(f"unexpected coding route: {path}")

    context.route("**/*", boundary)
    page = context.new_page()
    page.on("pageerror", lambda error: events["errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["errors"].append(message.text) if message.type == "error" else None,
    )
    page.on("requestfailed", lambda request: events["failed_requests"].append(request.url))
    page.set_default_timeout(15_000)
    label = f"{width}-{theme}"

    def show_runs():
        if width == 390 and not page.locator(".acw-rail").is_visible():
            page.locator("#aide-coding-runs-back").click()

    def choose(key):
        show_runs()
        page.locator(f'.acw-run-option[data-run-id="{key}"]').click()
        expect(page.locator("#aide-coding-record-id")).to_have_text(key)

    def new_run():
        show_runs()
        page.locator("#aide-coding-new").click()

    def hold(path):
        page.evaluate("path => { window.__holdCodingReply = path; }", path)

    def waiting():
        page.wait_for_function("typeof window.__releaseCodingReply === 'function'")

    def release(form):
        page.evaluate("window.__releaseCodingReply()")
        expect(page.locator(form).locator('button[type="submit"]')).to_be_enabled()

    try:
        assert context.request.post(BASE + "/api/setup/dismiss").ok
        assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.locator("#aide-mode-coding").click()
        expect(page.locator("#aide-coding-detail-title")).to_have_text("saved coding run a")

        for destination in ["another run", "new draft"]:
            followup = page.get_by_label("follow-up", exact=True)
            followup.fill("submitted follow-up")
            hold("/api/aide/coding/runs/a/continue")
            page.get_by_role("button", name="send follow-up", exact=True).click()
            waiting()
            draft = "newer unsent follow-up before " + destination
            followup.fill(draft)
            if destination == "another run":
                choose("b")
            else:
                new_run()
            release("#aide-coding-followup")
            choose("a")
            expect(followup).to_have_value(draft)
        page.screenshot(path=str(OUT / f"retained-followup-{label}.png"))

        new_run()
        page.get_by_label("instruction", exact=True).fill("late run while another run is selected")
        hold("/api/aide/coding/runs")
        page.get_by_role("button", name="start in DSH", exact=True).click()
        waiting()
        choose("b")
        expect(page.locator("#aide-coding-detail-title")).to_be_focused()
        release("#aide-coding-start")
        expect(page.locator("#aide-coding-detail-title")).to_have_text("saved coding run b")
        expect(page.locator("#aide-coding-detail-title")).to_be_focused()
        expect(page.locator(".acw-run-option")).to_have_count(3)
        page.screenshot(path=str(OUT / f"retained-selection-{label}.png"))

        new_run()
        page.get_by_label("instruction", exact=True).fill("late run after leaving coding")
        hold("/api/aide/coding/runs")
        page.get_by_role("button", name="start in DSH", exact=True).click()
        waiting()
        page.locator("#aide-mode-conversation").click()
        page.locator("#aide-mode-conversation").focus()
        release("#aide-coding-start")
        expect(page.locator("#aide-coding-workspace")).to_be_hidden()
        expect(page.locator("#aide-mode-conversation")).to_be_focused()
        expect(page.locator("#aide-coding-draft")).not_to_have_attribute("hidden", "")
        expect(page.locator(".acw-run-option")).to_have_count(4)
        page.screenshot(path=str(OUT / f"retained-conversation-{label}.png"))
        assert not any(events.values()), events
        return {"profile": label, "scenarios": 4, "events": events}
    finally:
        context.close()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    try:
        results = [run(browser, 1440, "dark"), run(browser, 390, "light")]
    finally:
        browser.close()
(OUT / "scenarios.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results), flush=True)

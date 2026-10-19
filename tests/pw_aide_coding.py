"""Visual and interaction gate for Aide code with pi (the runner's fake pi, real app UI)."""

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]

from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
events = {"console": [], "page_errors": [], "failed_requests": [], "external": []}
scenarios = []
workdir = tempfile.TemporaryDirectory(prefix="alles-pi-project-")
project_dir = Path(workdir.name) / "site"
(project_dir / "src").mkdir(parents=True)
(project_dir / "notes.txt").write_text("hello")


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


def watch(page):
    page.set_default_timeout(15_000)
    page.on(
        "console",
        lambda message: events["console"].append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "requestfailed",
        lambda request: (
            # a live stream closing when the view changes is expected
            None
            if request.url.endswith("/live") or "/live?" in request.url
            else events["failed_requests"].append({"url": request.url, "failure": request.failure})
        ),
    )


def wait_idle(page):
    expect(page.locator("#aide-coding-workspace")).to_have_attribute(
        "data-busy", "false", timeout=20_000
    )


def small_targets(page):
    return page.evaluate("""() => [...document.querySelectorAll('#aide-coding-workspace button, #aide-coding-workspace summary')]
      .filter(node => node.getClientRects().length && !node.closest('[hidden]'))
      .map(node => [node.id || node.className || node.textContent.trim(), node.getBoundingClientRect().height])
      .filter(([, height]) => height < 44)""")


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            desktop = context_for(browser, width=1440, theme="dark")
            request = desktop.request
            assert request.post(base + "/api/setup/dismiss").ok
            endpoint = request.post(
                base + "/api/models/endpoint",
                data={
                    "name": "fixture models",
                    "base_url": "http://127.0.0.1:9",
                    "api_key": "fixture",
                    "provider_adapter": "manual",
                },
            ).json()
            assert request.patch(
                base + f"/api/models/endpoint/{endpoint['id']}",
                data={"models": ["fixture-coder", "fixture-fast"]},
            ).ok
            page = desktop.new_page()
            watch(page)
            page.goto(base + "/?view=chat", wait_until="networkidle")
            coding = page.locator("#aide-mode-coding")
            coding.focus()
            coding.press("Enter")
            expect(page.locator("#aide-code-start")).to_be_visible()
            page.screenshot(path=str(out / "aide-coding-empty-dark.png"))

            # add the project with the folder picker, by keyboard
            page.locator("#aide-code-start-add").press("Enter")
            path = page.locator("#aide-code-folder-path")
            expect(path).to_be_focused()
            path.fill(str(project_dir))
            path.press("Enter")
            expect(page.locator("#aide-code-folders .acw-folder")).to_have_text(["src"])
            page.locator("#aide-code-folders .acw-folder").click()
            expect(path).to_have_value(str((project_dir / "src").resolve()))
            page.locator("#aide-code-folder-up").click()
            expect(path).to_have_value(str(project_dir.resolve()))
            page.screenshot(path=str(out / "aide-coding-add-dark.png"))
            page.locator("#aide-code-folder-use").click()
            expect(page.locator(".acw-project-name")).to_have_text(["site"])
            expect(page.locator("#aide-code-input")).to_be_focused()
            expect(page.locator("#aide-code-model-label")).to_have_text("fixture-coder")

            # a chat runs live: user message, tool row, streamed answer, stats
            expect(page.locator("#aide-code-send")).to_be_disabled()
            page.locator("#aide-code-input").fill("fix the header")
            page.locator("#aide-code-input").press("Enter")
            expect(page.locator(".acw-user")).to_have_text(["fix the header"])
            expect(page.locator(".acw-assistant").last).to_have_text(
                "done with fix the header", timeout=20_000
            )
            wait_idle(page)
            expect(page.locator(".acw-tool .acw-tool-name")).to_have_text(["read notes.txt"])
            expect(page.locator("#aide-code-stats")).to_contain_text("tok/s")
            expect(page.locator("#aide-code-stats")).to_contain_text("cache 75%")
            expect(page.locator(".acw-chat-title")).to_have_text(["fix the header"])
            page.locator(".acw-tool summary").click()
            expect(page.locator(".acw-tool-output")).to_have_text("hello from notes")
            page.screenshot(path=str(out / "aide-coding-chat-dark.png"))

            # the model menu works by keyboard and switches the running chat
            page.locator("#aide-code-model").press("Enter")
            expect(page.locator("#aide-code-model-menu")).to_be_visible()
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            expect(page.locator("#aide-code-model-label")).to_have_text("fixture-fast")
            expect(page.locator("#aide-code-model")).to_be_focused()

            # pi asks: the question shows above the composer and the answer goes back
            page.locator("#aide-code-input").fill("ask before you start")
            page.locator("#aide-code-input").press("Enter")
            expect(page.locator("#aide-code-question")).to_contain_text("trust?")
            page.locator("#aide-code-question").get_by_role(
                "button", name="yes", exact=True
            ).click()
            expect(page.locator(".acw-assistant").last).to_have_text(
                "done with ask before you start trusted=True", timeout=20_000
            )
            wait_idle(page)

            # a long run stops
            page.locator("#aide-code-input").fill("slow refactor")
            page.locator("#aide-code-input").press("Enter")
            expect(page.locator("#aide-code-stop")).to_be_visible()
            page.locator("#aide-code-stop").click()
            wait_idle(page)
            expect(page.locator("#aide-code-stop")).to_be_hidden()
            expect(page.locator(".acw-note").last).to_have_text("stopped")
            assert not small_targets(page), small_targets(page)

            # a saved chat reopens after the page reloads
            page.reload(wait_until="networkidle")
            page.locator("#aide-mode-coding").click()
            expect(page.locator(".acw-user")).to_have_count(3)
            expect(page.locator(".acw-assistant").first).to_have_text("done with fix the header")
            scenarios.append(
                {
                    "scenario_id": "aide.coding-pi.desktop",
                    "status": "passed",
                    "checks": [
                        "1440px dark theme",
                        "keyboard folder picker with up and open",
                        "live tool row, streamed answer, tok/s and cache line",
                        "model menu by keyboard",
                        "question answered from the chat",
                        "stop ends a long run",
                        "saved chat reopens after reload",
                        "44px targets",
                    ],
                }
            )

            # new chat, then delete it
            page.locator("[data-new-chat]").click()
            expect(page.locator("#aide-code-title")).to_have_text("new chat")
            page.locator("#aide-code-input").fill("second job")
            page.locator("#aide-code-input").press("Enter")
            wait_idle(page)
            expect(page.locator(".acw-chat-title")).to_have_count(2)
            page.locator("#aide-code-delete").click()
            page.locator(".dialog-overlay [data-dialog-confirm]").click()
            expect(page.locator(".acw-chat-title")).to_have_count(1)
            expect(page.locator("#aide-code-title")).to_have_text("new chat")
            desktop.close()

            phone = context_for(browser, width=390, theme="light")
            page = phone.new_page()
            watch(page)
            page.goto(base + "/?view=chat", wait_until="networkidle")
            page.locator("#aide-mode-coding").tap()
            expect(page.locator(".acw-user").first).to_have_text("fix the header")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            expect(page.locator(".acw-rail")).to_be_hidden()
            page.screenshot(path=str(out / "aide-coding-phone-light.png"))
            page.locator("#aide-code-rail-back").tap()
            expect(page.locator(".acw-rail")).to_be_visible()
            expect(page.locator(".acw-main")).to_be_hidden()
            page.screenshot(path=str(out / "aide-coding-phone-rail-light.png"))
            page.locator(".acw-chat-title").first.tap()
            expect(page.locator(".acw-main")).to_be_visible()
            assert not small_targets(page), small_targets(page)
            scenarios.append(
                {
                    "scenario_id": "aide.coding-pi.phone",
                    "status": "passed",
                    "checks": [
                        "390px light theme",
                        "rail and chat as separate panes",
                        "no page overflow",
                    ],
                }
            )
            phone.close()
        finally:
            browser.close()
finally:
    workdir.cleanup()

assert not events["console"], events
assert not events["page_errors"], events
assert not events["failed_requests"], events
assert not events["external"], events
(out / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n", encoding="utf-8")
(out / "browser-events.json").write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")

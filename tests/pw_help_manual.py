"""Discoverable help, working destinations, focus and draft-safe navigation."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

VIEWS = {
    "today": "#today-view",
    "chat": "#chat",
    "andromeda": "#andromeda-view",
    "plan": "#plan-view",
    "tasks": "#tasks-view",
    "calendar": "#calendar-view",
    "wiki": "#wiki-view",
    "journal": "#docs-journal-section",
    "files": "#files-view",
    "files-gallery": "#photos-view",
    "mail": "#mail-view",
    "contacts": "#contacts-view",
    "books": "#books-view",
    "read": "#read-view",
    "health-overview": "#health-group-view",
    "habits": "#habits-view",
    "money": "#money-view",
    "imports": "#finance-view",
    "subs": "#subs-view",
    "finance-overview": "#finance-view",
    "vault": "#vault-view",
    "server": "#system-view",
    "server-backups": "#server-workbench-view",
}


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    profiles = [
        ("desktop", 1440),
        ("tablet", 768),
        ("phone", 390),
        ("zoom200", 1440),
        ("high-contrast", 1440),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, width in profiles:
            options = dict(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
                forced_colors="active" if name == "high-contrast" else "none",
            )
            if name == "zoom200":
                extension = output / "zoom-extension"
                extension.mkdir()
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    output / "zoom-browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(
                    is_mobile=width == 390, has_touch=width == 390, **options
                )
            external, errors = [], []

            def local_only(route):
                if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()

            context.route("**/*", local_only)
            context.add_init_script(
                "window.__helpMicRequests=0; if(navigator.mediaDevices) navigator.mediaDevices.getUserMedia=()=>{window.__helpMicRequests++;return Promise.reject(new Error('test never grants microphone access'));};"
            )
            assert context.request.post(base + "/api/setup/dismiss").ok
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_default_timeout(10000)
            page.goto(base, wait_until="networkidle")
            if name == "zoom200":
                worker = (
                    context.service_workers[0]
                    if context.service_workers
                    else context.wait_for_event("serviceworker")
                )
                assert (
                    worker.evaluate(
                        "async()=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);}"
                    )
                    == 2
                )
                page.wait_for_function("innerWidth===720 && devicePixelRatio===2")

            def open_help(topic=None):
                page.locator("#app-drawer-btn").click()
                page.locator("#app-drawer-help").click()
                expect(page.locator("#alles-help-dialog")).to_be_visible()
                if topic:
                    page.locator(f'[data-manual-topic="{topic}"]').click()

            open_help()
            close = page.locator("[data-manual-close]")
            expect(close).to_be_focused()
            page.keyboard.press("Shift+Tab")
            assert page.locator("#alles-help-dialog").evaluate(
                "e=>e.contains(document.activeElement)"
            )
            page.keyboard.press("Tab")
            expect(close).to_be_focused()
            search = page.locator("#alles-help-search")
            search.fill("microphone")
            expect(page.locator('[data-manual-topic="voice"]')).to_be_visible()
            search.fill("no-such-topic-725")
            expect(page.locator("#alles-help-article")).to_be_hidden()
            expect(page.locator("#alles-help-status")).to_contain_text("no topics match")
            search.fill("coding")
            expect(page.locator('[data-manual-topic="coding"]')).to_be_visible()
            search.fill("")
            page.locator('[data-manual-topic="voice"]').click()
            expect(page.locator("#alles-help-topic-title")).to_be_focused()
            assert page.evaluate(
                "document.documentElement.scrollWidth<=document.documentElement.clientWidth"
            )
            page.screenshot(path=str(output / f"help-{name}-voice.png"))
            page.locator("#alles-help-article").evaluate("e=>e.scrollTop=e.scrollHeight")
            page.screenshot(path=str(output / f"help-{name}-voice-end.png"))
            page.keyboard.press("Escape")
            expect(page.locator("#alles-help-dialog")).to_have_count(0)
            expect(page.locator("#app-drawer-btn")).to_be_focused()

            destinations = []
            if name == "desktop":
                topics = page.evaluate(
                    "async()=> (await import('/static/js/help_content.js?v=2')).helpTopics().map(t=>({id:t.id,actions:t.actions||[]}))"
                )
                for topic in topics:
                    for action in topic["actions"]:
                        open_help(topic["id"])
                        key = "view" if "view" in action else "pane"
                        page.locator(f'[data-manual-{key}="{action[key]}"]').click()
                        expect(page.locator("#alles-help-dialog")).to_have_count(0)
                        if key == "view":
                            expect(page.locator(VIEWS[action[key]])).to_be_visible()
                        else:
                            expect(page.locator("#s-pane-" + action[key])).to_be_visible()
                            page.locator("#settings-modal-close").click()
                        destinations.append(action[key])

            page.evaluate("window._navigateTo('finance-overview')")
            page.locator("#finance-help").click()
            expect(page.locator("#alles-help-topic-title")).to_have_text("finance")
            page.screenshot(path=str(output / f"help-{name}-finance.png"))
            page.keyboard.press("Escape")
            expect(page.locator("#finance-help")).to_be_focused()

            filename = "manual-draft-" + name + ".md"
            assert context.request.post(
                base + "/api/vault-md/file",
                data={"path": filename, "content": "# saved original\n"},
            ).ok
            page.goto(base + "/?view=wiki&doc=" + filename, wait_until="networkidle")
            page.locator("#wiki-edit-btn").click()
            page.locator("#wiki-source-btn").click()
            source = page.locator("#wiki-source")
            changed = "# keep this manual navigation draft\n"

            def fail_draft(route):
                if route.request.method == "PUT":
                    route.fulfill(status=503, json={"detail": "synthetic help draft outage"})
                else:
                    route.continue_()

            page.route("**/api/vault-md/safety/draft", fail_draft)
            source.fill(changed)
            open_help("home")
            page.locator('[data-manual-view="today"]').click()
            expect(page.locator("#wiki-save-state")).to_have_text("synthetic help draft outage")
            expect(source).to_be_visible()
            expect(source).to_have_value(changed)
            expect(page.locator("#today-view")).to_be_hidden()
            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            open_help("home")
            page.locator('[data-manual-view="today"]').click()
            expect(page.locator("#today-view")).to_be_visible()
            draft = context.request.get(
                base + "/api/vault-md/safety/draft", params={"path": filename}
            )
            assert draft.ok and draft.json()["draft"]["content"] == changed
            assert page.evaluate("window.__helpMicRequests") == 0
            assert not errors, errors
            assert not external, external
            results.append(
                {
                    "profile": name,
                    "status": "passed",
                    "destinations": destinations,
                    "draft_failure_and_retry": True,
                    "microphone_requests": 0,
                    "page_errors": errors,
                    "external_requests": external,
                }
            )
            (output / "scenarios.json").write_text(json.dumps(results, indent=2))
            context.close()
        browser.close()


if __name__ == "__main__":
    run()

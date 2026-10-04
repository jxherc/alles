"""Task completion feedback and retries on owned local data."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]]
profiles += [(1280, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
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
                    profile / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(**options)
            context.route(
                "**/*",
                lambda request: (
                    request.continue_()
                    if urlparse(request.request.url).netloc == urlparse(base).netloc
                    else request.abort()
                ),
            )
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "plan.task-completion-recovery",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                task = context.request.post(
                    base + "/api/tasks", data={"title": "owned completion fixture " + label}
                ).json()
                endpoint = base + "/api/tasks/" + task["id"]
                page.goto(base + "/?view=tasks", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")

                def fail(route):
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def lost(route):
                    response = route.fetch()
                    assert response.ok
                    fail(route)

                for fault in [fail, lost]:
                    for done in [True, False]:
                        tab = "active" if done else "done"
                        tab_button = page.locator(f'.tasks-tab[data-tab="{tab}"]')
                        if tab_button.get_attribute("aria-pressed") != "true":
                            tab_button.click()
                        check = page.locator(f'.task-item[data-id="{task["id"]}"] .task-check')
                        expect(check).to_be_visible()
                        page.route(endpoint, fault)
                        check.press("Enter")
                        message = (
                            "could not confirm task completion. try again."
                            if done
                            else "could not confirm reopening the task. try again."
                        )
                        expect(page.locator(".toast.error").last).to_have_text(message)
                        expect(check).to_be_enabled()
                        expect(check).to_have_attribute("data-kokuen-state-message", message)
                        page.screenshot(path=str(out / f"{label}-{fault.__name__}-{done}.png"))
                        page.unroute(endpoint, fault)
                        check.press("Enter")
                        expect(check).to_have_count(0)
                        response = context.request.get(
                            base + ("/api/tasks/done" if done else "/api/tasks")
                        )
                        assert sum(t["id"] == task["id"] for t in response.json()) == 1
                page.reload(wait_until="networkidle")
                expect(
                    page.locator(f'.task-item[data-id="{task["id"]}"] .task-check')
                ).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                assert len(console) == 4 and all(
                    "503" in message and "Failed to load resource" in message for message in console
                ), console
                row["checks"] = [
                    "completion-rejected",
                    "completion-lost",
                    "reopen-rejected",
                    "reopen-lost",
                    "keyboard-retry",
                    "persisted-on-reload",
                ]
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))

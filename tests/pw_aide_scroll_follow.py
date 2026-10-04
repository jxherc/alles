"""Jump-to-latest scope and scroll recovery with owned synthetic history."""

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
                "scenario_id": "aide.scroll-follow",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                empty = context.request.post(
                    base + "/api/sessions", data={"name": "owned empty task"}
                ).json()["id"]
                populated = context.request.post(
                    base + "/api/sessions", data={"name": "owned scroll history"}
                ).json()["id"]
                history = context.request.get(
                    base + "/api/sessions/" + populated + "/history"
                ).json()
                history["messages"] = [
                    {
                        "id": "owned-message-" + str(index),
                        "role": "user" if index % 2 == 0 else "assistant",
                        "content": ("synthetic local history line " + str(index) + "\n") * 7,
                        "meta": {},
                        "timestamp": "2032-11-06T14:30:00Z",
                    }
                    for index in range(12)
                ]
                page.route(
                    base + "/api/sessions/" + populated + "/history",
                    lambda route: route.fulfill(json=history),
                )
                page.goto(base + "/?view=chat#" + empty, wait_until="networkidle")
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

                draft = "keep this unsent local draft"
                field = page.locator("#composer-ta")
                jump = page.locator("#jump-latest")
                field.fill(draft)
                expect(jump).to_be_hidden()
                for view, marker in [("skills", "#skl-new"), ("scheduled", "#aide-scheduled-view")]:
                    page.evaluate("view => window._navigateTo(view)", view)
                    expect(page.locator(marker)).to_be_visible()
                    expect(jump).to_be_hidden()
                    page.evaluate("window._navigateTo('chat')")
                    expect(field).to_be_visible()
                    expect(field).to_have_value(draft)
                    expect(jump).to_be_hidden()

                def open_task(session_id):
                    sidebar = page.locator("#sidebar-toggle-btn")
                    if sidebar.get_attribute("aria-expanded") == "false":
                        sidebar.click()
                    page.locator(f'.session-item[data-id="{session_id}"] .session-open').click()

                open_task(populated)
                expect(page.locator("#messages .msg-row")).to_have_count(12)
                field.fill(draft)
                chat = page.locator("#chat")
                chat.evaluate(
                    "node => { node.scrollTop = node.scrollHeight; node.dispatchEvent(new Event('scroll')); }"
                )
                expect(jump).to_be_hidden()
                chat.evaluate(
                    "node => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); }"
                )
                expect(jump).to_be_visible()
                page.screenshot(path=str(out / f"{label}-scrolled.png"))
                for view, marker in [("skills", "#skl-new"), ("scheduled", "#aide-scheduled-view")]:
                    page.evaluate("view => window._navigateTo(view)", view)
                    expect(page.locator(marker)).to_be_visible()
                    expect(jump).to_be_hidden()
                    page.screenshot(path=str(out / f"{label}-{view}.png"))
                    page.evaluate("window._navigateTo('chat')")
                    expect(field).to_have_value(draft)
                    expect(jump).to_be_visible()
                jump.press("Enter")
                expect(jump).to_be_hidden()
                assert (
                    chat.evaluate("node => node.scrollHeight - node.clientHeight - node.scrollTop")
                    <= 1
                )
                expect(field).to_have_value(draft)
                # The next empty task must not inherit an earlier scroll control.
                open_task(empty)
                expect(page.locator("#messages .msg-row")).to_have_count(0)
                expect(field).to_have_value(draft)
                expect(jump).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                assert not console, console
                row.update(
                    status="passed",
                    native_zoom=zoom,
                    history="synthetic browser fixture; no model call",
                )
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

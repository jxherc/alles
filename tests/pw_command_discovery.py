"""Command discovery, visible keyboard selection and Compare or help navigation."""

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
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]] + [
    (1280, t, True) for t in ["dark", "light"]
]

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
                "scenario_id": "aide.compare-help-entry",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=chat", wait_until="networkidle")
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
                field = page.locator("#composer-ta")
                field.fill("/")
                popup = page.locator(".slash-popup")
                expect(popup).to_contain_text("open model compare")
                count = popup.locator(".slash-item").count()
                for _ in range(count - 1):
                    field.press("ArrowDown")
                selected = popup.locator(".slash-item.selected")
                pbox = popup.bounding_box()
                sbox = selected.bounding_box()
                assert (
                    sbox["y"] >= pbox["y"]
                    and sbox["y"] + sbox["height"] <= pbox["y"] + pbox["height"] + 1
                ), (pbox, sbox)
                page.screenshot(path=str(out / f"{label}-commands.png"))
                field.press("Escape")
                expect(popup).to_have_count(0)
                expect(field).to_be_focused()
                field.fill("/comp")
                popup = page.locator(".slash-popup")
                expect(popup).to_contain_text("open model compare")
                box = popup.bounding_box()
                page.screenshot(path=str(out / f"{label}-compare-entry.png"))
                assert box["x"] >= 0 and box["x"] + box["width"] <= page.evaluate("innerWidth"), box
                field.press("Tab")
                expect(field).to_have_value("/compare")
                field.press("Enter")
                expect(page.locator("#compare-input")).to_be_visible()
                page.locator("#compare-input").fill("owned comparison draft")
                page.locator("#compare-send-btn").click()
                expect(page.locator("#toast-container")).to_contain_text("select a model first")
                page.evaluate("window._navigateTo('chat')")
                field.fill("/help")
                field.press("Tab")
                field.press("Enter")
                expect(page.locator("#messages")).to_contain_text("slash commands")
                expect(page.locator("#messages")).to_contain_text("open model compare")
                page.screenshot(path=str(out / f"{label}-help.png"))
                assert not errors, errors
                assert not console, console
                row.update(
                    status="passed",
                    native_zoom=zoom,
                    navigation="actual slash command and local help; no model call",
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                context.set_offline(False)
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))

"""First model connection from Compare with owned synthetic configuration."""

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
                "scenario_id": "aide.model-setup",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                # Each profile starts with its own empty configuration.
                for ep in context.request.get(base + "/api/models").json():
                    assert context.request.delete(base + "/api/models/endpoint/" + ep["id"]).ok
                assert context.request.patch(base + "/api/settings", data={"model_roles": {}}).ok
                page.goto(base + "/?view=compare", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => { const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id) }"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")
                prompt = page.locator("#compare-input")
                prompt.fill("keep this local comparison draft")
                page.locator("#compare-send-btn").press("Enter")
                page.locator("#compare-model-setup").press("Enter")
                expect(page.locator("#s-ep-list")).not_to_be_empty()
                control = page.locator("#s-ep-add-details > summary")
                bounds = control.bounding_box()
                assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= page.evaluate(
                    "innerHeight"
                ), bounds
                expect(page.locator("#s-model-defaults-card")).to_be_hidden()
                page.screenshot(path=str(out / f"{label}-first-connection.png"))
                for _ in range(16):
                    if control.evaluate("node => node === document.activeElement"):
                        break
                    page.keyboard.press("Tab")
                expect(control).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("#s-ep-name")).to_be_visible()
                page.get_by_label("connection name", exact=True).fill("owned setup connection")
                page.get_by_label("base url", exact=True).fill(base)
                for control_id in ("s-ep-adapter", "s-ep-auth"):
                    page.locator("#" + control_id).focus()
                    page.keyboard.press("End")
                    page.keyboard.press("Enter")
                page.locator("#s-ep-manual").fill("owned-synthetic-model")
                # No provider call: reject only the first local configuration write.
                attempts = []

                def create_connection(route):
                    attempts.append(route.request.post_data_json)
                    if len(attempts) == 1:
                        route.fulfill(
                            status=503, json={"detail": "synthetic local save unavailable"}
                        )
                    else:
                        route.continue_()

                page.route(base + "/api/models/endpoint", create_connection)
                page.locator("#s-ep-add-btn").click()
                expect(page.locator("#s-ep-add-btn")).to_be_enabled()
                expect(page.locator("#toast-container")).to_contain_text(
                    "synthetic local save unavailable"
                )
                expect(page.locator("#s-ep-name")).to_have_value("owned setup connection")
                expect(page.locator("#s-ep-manual")).to_have_value("owned-synthetic-model")
                page.locator("#s-ep-add-btn").click()
                expect(page.locator("#s-model-defaults-card")).to_be_visible()
                expect(page.locator("#s-ep-add-details")).not_to_have_attribute("open", "")
                endpoints = context.request.get(base + "/api/models").json()
                assert len(endpoints) == 1 and endpoints[0]["models"] == [
                    "owned-synthetic-model"
                ], endpoints
                role = page.locator('[data-role-select="aide_chat"]')
                role.focus()
                page.keyboard.press("End")
                page.keyboard.press("Enter")
                page.locator("#s-role-save-btn").click()
                expect(page.locator("#s-role-save-btn")).to_be_enabled()
                assert (
                    context.request.get(base + "/api/settings").json()["model_roles"]["aide_chat"][
                        "model"
                    ]
                    == "owned-synthetic-model"
                )
                page.keyboard.press("Escape")
                expect(page.locator("#compare-model-setup")).to_be_focused()
                expect(prompt).to_have_value("keep this local comparison draft")
                page.locator("#compare-model-setup").press("Enter")
                expect(page.locator("#s-model-defaults-card")).to_be_visible()
                expect(role).not_to_have_attribute("aria-invalid", "true")
                page.screenshot(path=str(out / f"{label}-saved-default.png"))
                page.keyboard.press("Escape")
                assert context.request.delete(
                    base + "/api/models/endpoint/" + endpoints[0]["id"]
                ).ok
                page.locator("#compare-model-setup").press("Enter")
                expect(role).to_have_attribute("aria-invalid", "true")
                expect(page.locator("#s-model-defaults-card")).to_be_visible()
                expect(page.locator("#s-model-roles")).to_contain_text("needs a replacement")
                page.screenshot(path=str(out / f"{label}-unavailable-default.png"))
                page.keyboard.press("Escape")
                expect(page.locator("#compare-model-setup")).to_be_focused()
                expect(prompt).to_have_value("keep this local comparison draft")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                unexpected = [message for message in console if "503" not in message]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    native_zoom=zoom,
                    provider="manual synthetic catalog; no model call",
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

"""Contextual shortcut help preserves drafts and reads the saved key bindings."""

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
                "is_mobile": width == 390,
                "has_touch": width == 390,
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
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "aide.shortcut-help",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            session_id = None
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
                field.fill("owned unsent question")
                help_button = page.locator("#aide-help")
                help_button.press("Enter")
                dialog = page.get_by_role("dialog", name="aide help", exact=True)
                close = dialog.get_by_role("button", name="close", exact=True)
                customize = dialog.get_by_role("button", name="customize shortcuts", exact=True)
                expect(dialog).to_be_visible()
                expect(close).to_be_focused()
                expect(help_button).to_have_attribute("aria-expanded", "true")
                expect(dialog).to_contain_text("Alt+N")
                expect(dialog).to_contain_text("start a new aide task")
                expect(dialog).to_contain_text("add a task to Plan")
                expect(field).to_have_value("owned unsent question")
                assert "start a new chat" not in dialog.inner_text()
                page.keyboard.press("Control+Enter")
                expect(dialog).to_be_visible()
                expect(field).to_have_value("owned unsent question")
                expect(page.locator("#composer-send-recovery")).to_be_hidden()
                page.keyboard.press("Shift+Tab")
                expect(customize).to_be_focused()
                page.keyboard.press("Tab")
                expect(close).to_be_focused()
                box = dialog.bounding_box()
                assert box["x"] >= 0 and box["y"] >= 0, box
                assert box["x"] + box["width"] <= page.evaluate("innerWidth"), box
                assert box["y"] + box["height"] <= page.evaluate("innerHeight"), box
                for control in [help_button, close, customize]:
                    bounds = control.bounding_box()
                    assert bounds["width"] >= 43.9 and bounds["height"] >= 43.9, bounds
                page.screenshot(path=str(out / f"{label}-help.png"))
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(0)
                expect(help_button).to_be_focused()
                expect(help_button).to_have_attribute("aria-expanded", "false")
                expect(field).to_have_value("owned unsent question")
                (help_button.tap if width == 390 else help_button.click)()
                customize.press("Enter")
                binding = page.locator('.shortcut-input[data-shortcut="new_chat"]')
                expect(binding).to_be_visible()
                expect(binding).to_be_focused()
                expect(page.get_by_label("new aide task", exact=True)).to_have_count(1)
                binding.press("Alt+j")
                expect(binding).to_have_value("Alt+J")
                page.locator("#settings-modal-close").click()
                expect(help_button).to_be_focused()
                help_button.press("Enter")
                expect(dialog).to_contain_text("Alt+J")
                assert "Alt+N" not in dialog.locator(".aide-help-shortcuts").inner_text()
                close.press("Enter")
                expect(help_button).to_be_focused()
                expect(field).to_have_value("owned unsent question")
                context.set_offline(True)
                help_button.press("Enter")
                expect(dialog).to_contain_text("start a new aide task")
                close.press("Enter")
                context.set_offline(False)
                expect(help_button).to_be_focused()
                expect(field).to_have_value("owned unsent question")
                page.screenshot(path=str(out / f"{label}-composer.png"))
                field.fill("/help")
                field.press("Tab")
                field.press("Enter")
                expect(page.locator("#messages")).to_contain_text("slash commands")
                expect(page.locator("#messages")).to_contain_text("start a new aide task")
                assert "start a new chat" not in page.locator("#messages").inner_text()
                session = context.request.post(base + "/api/sessions", data={"name": "new chat"})
                assert session.ok
                session_id = session.json()["id"]
                page.goto(base + "/?view=chat#" + session_id, wait_until="networkidle")
                page.reload(wait_until="networkidle")
                expect(page.locator("#aide-conversation-name")).to_have_text("new chat")
                page.keyboard.press("Alt+j")
                expect(page.locator("#aide-conversation-name")).to_have_text("new aide task")
                assert (
                    context.request.get(base + "/api/sessions/" + session_id + "/history").json()[
                        "session"
                    ]["name"]
                    == "new chat"
                )
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                assert not errors, errors
                assert not console, console
                row.update(status="passed", native_zoom=zoom, no_model_call=True)
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                context.set_offline(False)
                if session_id:
                    assert context.request.delete(base + "/api/sessions/" + session_id).ok
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))

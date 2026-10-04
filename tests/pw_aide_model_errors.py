"""Aide model HTTP errors and recovery guidance on an owned local application."""

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
profiles += [(1440, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
                "has_touch": width == 390,
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
            state = {"status": 404, "hold": True, "partial": ""}
            held, requests, errors, console = [], [], [], []

            def reply(route):
                chunks = []
                if state["partial"]:
                    chunks.append({"delta": state["partial"]})
                if state["status"]:
                    chunks.append(
                        {
                            "error": f'HTTP {state["status"]}: {{"detail":"synthetic local model failure"}}'
                        }
                    )
                else:
                    chunks.append({"delta": "successful synthetic local answer"})
                stream = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                route.fulfill(content_type="text/event-stream", body=stream + "data: [DONE]\n\n")

            def route(request):
                url = urlparse(request.request.url)
                if url.netloc != urlparse(base).netloc:
                    return request.abort()
                if url.path == "/api/chat" and request.request.method == "POST":
                    requests.append(request.request.post_data_json)
                    if state["hold"]:
                        held.append(request)
                        return None
                    return reply(request)
                return request.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.model-errors", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                endpoint = api.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned error fixture",
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert api.patch(
                    base + "/api/models/endpoint/" + endpoint["id"],
                    data={"models": ["local-error-fixture"]},
                ).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": endpoint["id"],
                        "default_model": "local-error-fixture",
                        "model_roles": {},
                        "memory_policy": "off",
                        "memory_auto_inject": False,
                        "intent_suggestions": False,
                        "auto_compact": False,
                    },
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
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                field = page.locator("#composer-ta")
                question = "original synthetic local question"
                field.fill(question)
                page.locator("#send-btn").click()
                expect(page.locator("#send-btn")).to_be_disabled()
                page.wait_for_timeout(50)
                assert len(held) == 1
                newer = "newer unsent draft stays exactly here"
                field.fill(newer)
                reply(held.pop())
                notice = page.locator(".error-msg.model-error").last
                expect(notice.get_by_role("status")).to_contain_text("model could not be found")
                expect(page.locator(".user-bubble").last).to_have_text(question)
                expect(field).to_have_value(newer)
                expect(field).to_be_focused()
                expect(page.locator("#conn-banner")).to_be_hidden()
                details = notice.locator("details")
                expect(details.locator("pre")).to_be_hidden()
                summary = details.locator("summary")
                summary.focus()
                page.keyboard.press("Enter")
                expect(details.locator("pre")).to_have_text(
                    'HTTP 404: {"detail":"synthetic local model failure"}'
                )
                page.screenshot(path=str(out / f"{label}-details.png"))
                page.keyboard.press("Enter")
                expect(details.locator("pre")).to_be_hidden()
                settings = notice.get_by_role("button", name="model settings", exact=True)
                if width == 390:
                    settings.tap()
                else:
                    settings.focus()
                    page.keyboard.press("Enter")
                expect(page.locator("#s-pane-models")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#settings-modal")).to_be_hidden()
                expect(settings).to_be_focused()
                expect(field).to_have_value(newer)
                assert len(requests) == 1, "settings must not retry the model automatically"
                assert (
                    notice.get_by_role("status").evaluate(
                        "el=>parseFloat(getComputedStyle(el).fontSize)"
                    )
                    >= 16
                )
                assert settings.bounding_box()["height"] >= 44
                assert summary.bounding_box()["height"] >= 44
                page.screenshot(path=str(out / f"{label}-recovery.png"))

                state["hold"] = False
                checks = [
                    (401, "did not authorize"),
                    (403, "did not authorize"),
                    (429, "reached its limit"),
                    (503, "temporarily unavailable"),
                    (400, "could not answer"),
                ]
                for status, explanation in checks:
                    state["status"] = status
                    state["partial"] = (
                        "partial synthetic answer stays visible" if status == 503 else ""
                    )
                    field.fill(f"synthetic local request {status}")
                    page.locator("#send-btn").click()
                    expect(page.locator(".model-error")).to_have_count(
                        1 + checks.index((status, explanation)) + 1
                    )
                    expect(notice.get_by_role("status")).to_contain_text(explanation)
                    expect(notice.locator("pre")).to_contain_text(f"HTTP {status}")
                    if status == 503:
                        expect(page.locator(".ai-content").last).to_contain_text(state["partial"])
                    expect(page.locator("#send-btn")).to_be_enabled()
                state.update(status=0, partial="")
                field.fill(question)
                page.locator("#send-btn").click()
                expect(page.locator(".ai-content").last).to_have_text(
                    "successful synthetic local answer"
                )
                expect(page.locator("#send-btn")).to_be_enabled()
                assert requests[-1]["message"] == question
                assert len(requests) == 7
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert not errors, errors
                assert not console, console
                page.screenshot(path=str(out / f"{label}-answered.png"))
                row.update(
                    status="passed",
                    requests=len(requests),
                    page_errors=errors,
                    console_errors=console,
                )
            except Exception as error:
                row.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                )
                page.screenshot(path=str(out / f"{label}-failed.png"))
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    finally:
        browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"

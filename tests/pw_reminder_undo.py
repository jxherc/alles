"""Reminder undo and uncertain response recovery on owned local data."""

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
                "scenario_id": "plan.reminder-undo",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                original = context.request.post(
                    base + "/api/reminders",
                    data={
                        "text": "owned exact reminder 中文\nsecond line " + label,
                        "trigger_at": "2032-11-06T14:35:17.123456Z",
                    },
                ).json()
                endpoint = base + "/api/reminders/" + original["id"]
                page.goto(base + "/?view=reminders", wait_until="networkidle")
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

                requests = []
                page.on(
                    "request",
                    lambda request: (
                        requests.append(request.post_data_json)
                        if request.url == base + "/api/reminders" and request.method == "POST"
                        else None
                    ),
                )
                page.route(endpoint, lost)
                page.locator(f'[data-reminder-cancel="{original["id"]}"]').press("Enter")
                expect(page.locator(".toast.error")).to_be_visible()
                page.unroute(endpoint, lost)
                # A refresh after the lost delete must not erase the cancellation recovery action.
                page.evaluate("import('/static/js/reminders.js?v=243').then(m=>m.loadReminders())")
                expect(page.locator(f'[data-reminder-cancel="{original["id"]}"]')).to_have_count(0)
                recover = page.locator(f'[data-reminder-recover="{original["id"]}"]')
                expect(recover).to_have_text("retry cancel")

                def denied(route):
                    route.fulfill(
                        status=403,
                        content_type="application/json",
                        body='{"detail":"synthetic denied"}',
                    )

                page.route(endpoint, denied)
                with page.expect_response(endpoint):
                    recover.press("Enter")
                expect(recover).to_be_visible()
                page.unroute(endpoint, denied)
                recover.press("Enter")
                expect(recover).to_have_text("undo")
                expect(page.locator("#reminder-undo-list")).to_contain_text(original["text"])
                page.screenshot(path=str(out / f"{label}-cancelled.png"))
                page.route(base + "/api/reminders", fail)
                recover.press("Enter")
                expect(recover).to_have_text("retry undo")
                expect(recover).to_be_enabled()
                page.unroute(base + "/api/reminders", fail)
                page.route(base + "/api/reminders", lost)
                recover.press("Enter")
                expect(recover).to_have_text("retry undo")
                expect(recover).to_be_enabled()
                page.unroute(base + "/api/reminders", lost)
                restored = [
                    r
                    for r in context.request.get(base + "/api/reminders").json()
                    if r["text"] == original["text"]
                ]
                assert len(restored) == 1
                sibling = context.request.post(
                    base + "/api/reminders",
                    data={"text": "owned sibling " + label, "trigger_at": "2032-11-06T14:35:17Z"},
                ).json()
                page.evaluate("import('/static/js/reminders.js?v=243').then(m=>m.loadReminders())")
                page.locator(f'[data-reminder-cancel="{sibling["id"]}"]').press("Enter")
                dismiss = page.locator(f'[data-reminder-dismiss="{sibling["id"]}"]')
                expect(dismiss).to_be_enabled()
                held = []

                def hold(route):
                    held.append((route, route.fetch()))

                page.route(base + "/api/reminders", hold)
                recover.press("Enter")
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(10)
                assert len(held) == 1
                expect(recover).to_be_disabled()
                dismiss.focus()
                held[0][0].fulfill(response=held[0][1])
                expect(recover).to_have_count(0)
                expect(dismiss).to_be_focused()
                page.unroute(base + "/api/reminders", hold)
                dismiss.press("Enter")

                actual = [
                    r
                    for r in context.request.get(base + "/api/reminders").json()
                    if r["text"] == original["text"]
                ]
                assert len(actual) == 1 and actual[0]["id"] == restored[0]["id"]
                assert actual[0]["id"] != original["id"]
                assert all(
                    actual[0][key] == original[key]
                    for key in ["text", "trigger_at", "type", "session_id"]
                )
                assert len(requests) == 3 and len({r["request_id"] for r in requests}) == 1
                page.reload(wait_until="networkidle")
                expect(page.locator(f'[data-reminder-cancel="{actual[0]["id"]}"]')).to_be_visible()
                # A normal cancellation can be dismissed without recreating the reminder.
                page.locator(f'[data-reminder-cancel="{actual[0]["id"]}"]').press("Enter")
                expect(page.locator(f'[data-reminder-recover="{actual[0]["id"]}"]')).to_have_text(
                    "undo"
                )
                page.locator(f'[data-reminder-dismiss="{actual[0]["id"]}"]').press("Enter")
                expect(page.locator("#reminder-undo-list")).to_be_hidden()
                expect(page.locator("#reminder-text")).to_be_focused()
                assert not [
                    r
                    for r in context.request.get(base + "/api/reminders").json()
                    if r["text"] == original["text"]
                ]

                endpoint_response = context.request.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned reminder fixture",
                        "base_url": base + "/v1",
                        "provider_adapter": "manual",
                    },
                )
                assert endpoint_response.ok
                eid = endpoint_response.json()["id"]
                assert context.request.patch(
                    base + "/api/models/endpoint/" + eid, data={"models": ["fixture"]}
                ).ok
                conversation = context.request.post(
                    base + "/api/sessions",
                    data={"name": "owned schedule", "model": "fixture", "endpoint_id": eid},
                ).json()
                for past in [False, True]:
                    scheduled = context.request.post(
                        base + "/api/reminders",
                        data={
                            "text": "owned scheduled message " + label + str(past),
                            "type": "message",
                            "session_id": conversation["id"],
                            "trigger_at": "2001-11-06T14:35:17Z"
                            if past
                            else "2032-11-06T14:35:17Z",
                        },
                    ).json()
                    page.evaluate(
                        "import('/static/js/reminders.js?v=243').then(m=>m.loadReminders())"
                    )
                    page.locator(f'[data-reminder-cancel="{scheduled["id"]}"]').press("Enter")
                    undo = page.locator(f'[data-reminder-recover="{scheduled["id"]}"]')
                    expect(undo).to_have_text("undo")
                    before = len(requests)
                    undo.press("Enter")
                    if past:
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_contain_text("will send it now")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        expect(undo).to_be_enabled()
                        expect(undo).to_be_focused()
                        assert len(requests) == before
                        undo.press("Enter")
                        dialog.get_by_role("button", name="confirm", exact=True).press("Enter")
                    expect(undo).to_have_count(0)
                    restored_message = [
                        r
                        for r in context.request.get(base + "/api/reminders").json()
                        if r["text"] == scheduled["text"]
                    ]
                    assert len(restored_message) == 1
                    assert all(
                        restored_message[0][k] == scheduled[k]
                        for k in ["text", "type", "session_id", "trigger_at"]
                    )
                    assert len(requests) == before + 1
                    assert context.request.delete(
                        base + "/api/reminders/" + restored_message[0]["id"]
                    ).ok
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                assert len(console) == 5 and all(
                    str(status) in message and "Failed to load resource" in message
                    for message, status in zip(console, [503, 403, 404, 503, 503])
                ), console
                row["checks"] = [
                    "cancel-lost-refresh-retry",
                    "denied-retry-keeps-uncertainty",
                    "dismiss-focus-during-restore",
                    "undo-rejected",
                    "undo-lost",
                    "same-identity-retry",
                    "exact-content-and-microseconds",
                    "keyboard",
                    "persisted-on-reload",
                    "dismiss-cancellation",
                    "scheduled-message-restoration",
                    "past-message-confirmation",
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

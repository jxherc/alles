"""Calendar quick-add exact undo, pending requests and recovery on owned local data."""

import base64
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
                "is_mobile": width == 390,
                "has_touch": width == 390,
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
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)

            def capture(name):
                shot = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{name}.png").write_bytes(base64.b64decode(shot["data"]))

            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "calendar.quick-undo",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=calendar", wait_until="networkidle")
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
                quick = page.locator("#cal-quick")
                if not quick.is_visible():
                    page.locator("#cal-tools-toggle").click()
                expect(quick).to_be_visible()
                undo = page.locator("#cal-quick-undo")
                status = page.locator("#cal-quick-status")
                endpoint = base + "/api/calendar/quick"

                def action(control):
                    control.tap() if width == 390 else control.click()

                def saved():
                    result = context.request.get(base + "/api/calendar")
                    assert result.ok
                    return {event["id"]: event for event in result.json()}

                def create(title):
                    quick.fill(title + " tomorrow 1pm")
                    with page.expect_response(
                        lambda r: r.url == endpoint and r.request.method == "POST"
                    ) as response:
                        quick.press("Enter")
                    assert response.value.ok
                    expect(undo).to_be_visible()
                    expect(undo).to_have_attribute("aria-disabled", "false")
                    event = response.value.json()
                    expect(status).to_have_text("added “" + event["title"] + "”")
                    return event

                def removed(event):
                    expect(status).to_have_text("removed “" + event["title"] + "”")
                    expect(undo).to_be_hidden()
                    expect(quick).to_have_attribute("aria-busy", "false")
                    assert event["id"] not in saved()

                held = []

                def delayed_create(route):
                    held.append((route, route.fetch()))

                page.route(endpoint, delayed_create)
                quick.fill("owned first " + label + " tomorrow 1pm")
                quick.press("Enter")
                expect(quick).to_have_attribute("aria-busy", "true")
                quick.press("Enter")
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(50)
                assert len(held) == 1
                event = held[0][1].json()
                page.locator("#cal-new-btn").click()
                page.locator("#cal-title").fill("new draft while quick-add is pending")
                page.locator("#cal-desc").fill("retain these later details")
                held[0][0].fulfill(response=held[0][1])
                expect(undo).to_have_attribute("aria-disabled", "false")
                expect(undo).to_be_visible()
                expect(page.locator("#cal-desc")).to_have_value("retain these later details")
                expect(page.locator("#cal-desc")).to_be_focused()
                page.locator("#cal-back").scroll_into_view_if_needed()
                capture("pending-editor")
                page.locator("#cal-back").click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(page.locator("#cal-title")).to_have_count(0)
                quick.focus()
                expect(quick).to_be_focused()
                assert event["id"] in saved()
                page.unroute(endpoint, delayed_create)
                target = base + "/api/calendar/" + event["id"]

                def failed_undo(route):
                    route.fulfill(status=503, json={"detail": "synthetic undo unavailable"})

                page.route(target, failed_undo)
                undo.focus()
                page.keyboard.press("Enter")
                expect(status).to_have_text(
                    "could not confirm removing “" + event["title"] + "”. try undo again."
                )
                expect(undo).to_be_focused()
                expect(undo).to_have_attribute("aria-disabled", "false")
                assert event["id"] in saved()
                capture("undo-retry")
                page.unroute(target, failed_undo)
                page.keyboard.press("Enter")
                removed(event)
                expect(quick).to_be_focused()
                keep = create("owned keep " + label)
                last = create("owned latest " + label)
                target = base + "/api/calendar/" + last["id"]

                def lost_ack(route):
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(response=response, json={})

                page.route(target, lost_ack)
                action(undo)
                expect(status).to_contain_text("could not confirm removing")
                assert last["id"] not in saved() and keep["id"] in saved()
                page.unroute(target, lost_ack)
                action(undo)
                removed(last)
                assert keep["id"] in saved()

                def failed_list(route):
                    route.fulfill(status=503, json={"detail": "synthetic list unavailable"})

                page.route(base + "/api/calendar", failed_list)
                refresh = create("owned saved before refresh failure " + label)
                expect(page.locator("#cal-load-error")).to_be_visible()
                assert refresh["id"] in saved()
                action(undo)
                removed(refresh)
                expect(page.locator("#cal-load-error")).to_be_visible()
                page.unroute(base + "/api/calendar", failed_list)

                def failed_create(route):
                    route.fulfill(status=503, json={"detail": "synthetic create unavailable"})

                page.route(endpoint, failed_create)
                text = "owned retained input " + label + " tomorrow 2pm"
                quick.fill(text)
                quick.press("Enter")
                expect(status).to_have_text(
                    "event not confirmed. your text is still here. check the calendar before trying again."
                )
                expect(quick).to_have_value(text)
                expect(undo).to_be_hidden()
                expect(quick).to_have_attribute("aria-busy", "false")
                page.unroute(endpoint, failed_create)
                final = create("owned final " + label)
                capture("added")
                held_list = []

                def delayed_list(route):
                    held_list.append((route, route.fetch()))

                page.route(base + "/api/calendar", delayed_list)
                action(undo)
                for _ in range(100):
                    if held_list:
                        break
                    page.wait_for_timeout(50)
                assert len(held_list) == 1
                page.locator("#cal-new-btn").click()
                page.locator("#cal-title").fill("new draft while undo refresh is pending")
                page.locator("#cal-desc").fill("retain the draft through list refresh")
                held_list[0][0].fulfill(response=held_list[0][1])
                removed(final)
                expect(page.locator("#cal-desc")).to_have_value(
                    "retain the draft through list refresh"
                )
                expect(page.locator("#cal-desc")).to_be_focused()
                page.unroute(base + "/api/calendar", delayed_list)
                page.locator("#cal-back").click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(page.locator("#cal-title")).to_have_count(0)
                assert keep["id"] in saved()
                page.reload(wait_until="networkidle")
                assert keep["id"] in saved()
                assert not errors, errors
                assert len(console) == 5 and all(
                    "Failed to load resource" in item
                    and any(str(code) in item for code in [503, 404])
                    for item in console
                ), console
                row.update(
                    status="passed",
                    kept_event=keep["id"],
                    removed_events=[event["id"], last["id"], refresh["id"], final["id"]],
                    pending_creates=len(held),
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
                capture("failure")
            finally:
                row.update(page_errors=errors, console_errors=console)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))

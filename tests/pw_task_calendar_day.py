"""Task urgency, staged dates and saved outcomes share Home's configured calendar."""

import base64
import json
import os
import struct
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    cases = [
        ("automatic-west", "America/Toronto", "", "2026-10-06T00:50:00+00:00"),
        ("configured-east", "UTC", "Asia/Tokyo", "2026-10-05T23:30:00+00:00"),
    ]
    profiles = [
        (case, width, theme, False)
        for case in cases
        for width in (1440, 390)
        for theme in ("light", "dark")
    ]
    profiles += [
        (
            ("configured-west", "Asia/Tokyo", "America/Toronto", "2026-10-06T00:50:00+00:00"),
            1440,
            theme,
            True,
        )
        for theme in ("light", "dark")
    ]
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for (case, browser_zone, configured, timestamp), width, theme, zoom in profiles:
                instant = datetime.fromisoformat(timestamp)
                day = instant.astimezone(ZoneInfo(configured or browser_zone)).date()
                tomorrow = (day + timedelta(days=1)).isoformat()
                label = f"{case}-{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    viewport={"width": width, "height": 900},
                    timezone_id=browser_zone,
                    service_workers="block",
                    reduced_motion="reduce",
                    has_touch=width == 390,
                )
                if zoom:
                    profile = Path(os.environ["ALLES_DATA"]) / label
                    extension = profile / "extension"
                    extension.mkdir(parents=True)
                    (extension / "manifest.json").write_text(
                        json.dumps(
                            dict(
                                manifest_version=3,
                                name="owned zoom check",
                                version="1.0",
                                permissions=["tabs"],
                                background={"service_worker": "zoom.js"},
                            )
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
                errors, console, external = [], [], []

                def guard(route):
                    target = urlsplit(route.request.url)
                    if (target.scheme, target.netloc) != ("http", urlsplit(base).netloc):
                        external.append(route.request.url)
                        return route.abort()
                    return route.continue_()

                context.route("**/*", guard)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.clock.set_fixed_time(instant)
                page.set_default_timeout(6000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                api = context.request
                record = dict(
                    profile=label,
                    status="failed",
                    browser_zone=browser_zone,
                    configured_zone=configured,
                    instant=timestamp,
                    calendar_day=day.isoformat(),
                )
                records.append(record)
                saved = None

                def capture(name):
                    png = base64.b64decode(
                        context.new_cdp_session(page).send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )["data"]
                    )
                    assert struct.unpack("!II", png[16:24]) == (width, 900)
                    (out / f"{label}-{name}.png").write_bytes(png)

                def stored():
                    for endpoint in ("/api/tasks", "/api/tasks/done"):
                        response = api.get(base + endpoint)
                        assert response.ok, response.text()
                        for task in response.json():
                            if task["id"] == saved["id"]:
                                return task
                    raise AssertionError("saved task missing from active and done lists")

                try:
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(
                        base + "/api/settings", data={"timezone": configured, "language": "en"}
                    ).ok
                    page.goto(base + "/?view=today", wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                        record["native_zoom"] = dict(factor=2, css_width=720, dpr=2)
                    expect(page.locator("#today-date")).to_have_text(
                        f"{day.strftime('%A').lower()}, {day.strftime('%B').lower()} {day.day}"
                    )
                    page.locator("#today-capture-input").fill("review reading tomorrow")
                    page.locator("#today-capture-input").press("Enter")
                    expect(page.locator("#capture-title")).to_have_value("review reading")
                    assert page.locator("#capture-due").evaluate("e=>e.value") == tomorrow
                    with page.expect_response(
                        lambda r: r.url == base + "/api/tasks" and r.request.method == "POST"
                    ) as accepted:
                        page.locator("#capture-accept").press("Enter")
                    assert accepted.value.ok
                    saved = accepted.value.json()
                    assert saved["due_date"] == tomorrow
                    page.locator("#capture-open").press("Enter")
                    expect(page.locator("#te-due")).to_have_value(tomorrow)
                    page.locator("#te-cancel").press("Enter")
                    row = page.locator(f'.task-item[data-id="{saved["id"]}"]')
                    expect(page.locator(".task-editor")).to_have_count(0)
                    expect(row.locator(".task-due")).to_have_text("tomorrow")
                    assert "today" not in row.locator(".task-due").get_attribute("class")
                    capture("tomorrow")
                    row.locator(".task-title").press("Enter")
                    page.locator('.te-rs[data-w="today"]').press("Enter")
                    expect(page.locator("#te-due")).to_have_value(day.isoformat())
                    page.locator("#te-cancel").press("Enter")
                    page.locator("[data-dialog-confirm]").press("Enter")
                    expect(row.locator(".task-title")).to_be_focused()
                    assert stored()["due_date"] == tomorrow
                    row.locator(".task-title").press("Enter")
                    page.locator('.te-rs[data-w="today"]').press("Enter")
                    endpoint = base + "/api/tasks/" + saved["id"]

                    def unavailable(route):
                        if route.request.method == "PATCH":
                            route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"synthetic save unavailable"}',
                            )
                        else:
                            route.continue_()

                    page.route(endpoint, unavailable)
                    page.locator("#te-save").press("Enter")
                    expect(page.locator(".task-recovery-message")).to_contain_text(
                        "save not confirmed"
                    )
                    expect(page.locator("#te-due")).to_have_value(day.isoformat())
                    assert stored()["due_date"] == tomorrow
                    capture("save-recovery")
                    page.unroute(endpoint, unavailable)
                    page.locator("#te-save").press("Enter")
                    expect(row.locator(".task-due.today")).to_have_text("today")
                    expect(row.locator(".task-title")).to_be_focused()
                    assert stored()["due_date"] == day.isoformat()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#te-due")).to_have_value(day.isoformat())
                    page.locator("#te-cancel").press("Enter")
                    expect(page.locator(".task-editor")).to_have_count(0)
                    expect(row.locator(".task-due.today")).to_have_text("today")
                    row.locator(".task-title").press("Enter")
                    page.locator('.te-rs[data-w="tomorrow"]').press("Enter")
                    expect(page.locator("#te-due")).to_have_value(tomorrow)
                    page.locator("#te-save").press("Enter")
                    expect(row.locator(".task-due")).to_have_text("tomorrow")
                    assert stored()["due_date"] == tomorrow
                    capture("rescheduled")
                    page.clock.set_fixed_time(instant + timedelta(days=1))
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#te-due")).to_have_value(tomorrow)
                    page.locator("#te-cancel").press("Enter")
                    expect(page.locator(".task-editor")).to_have_count(0)
                    assert not page.locator(".app").evaluate("e=>e.inert")
                    expect(row.locator(".task-due.today")).to_have_text("today")
                    assert stored()["due_date"] == tomorrow
                    capture("next-local-day")
                    row.locator(".task-check").click()
                    expect(page.locator("#task-completion-undo")).to_be_focused()
                    assert stored()["done"]
                    page.locator("#task-completion-undo").press("Enter")
                    expect(row.locator(".task-due.today")).to_have_text("today")
                    assert not stored()["done"] and stored()["due_date"] == tomorrow
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    capture("reopened")
                    assert not errors and not external
                    assert console and all(
                        "status of 503 (Service Unavailable)" in text for text in console
                    ), console
                    record.update(
                        status="passed",
                        actual_capture=True,
                        cancel_without_write=True,
                        save_failure_recovery=True,
                        reschedule_and_reload=True,
                        next_local_day=True,
                        completion_and_undo=True,
                    )
                except Exception:
                    record["failure"] = traceback.format_exc()
                    capture("failure")
                finally:
                    if saved:
                        assert api.delete(base + "/api/tasks/" + saved["id"]).ok
                    record.update(page_errors=errors, console_errors=console, external=external)
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
        finally:
            browser.close()
    assert len(records) == 10 and all(row["status"] == "passed" for row in records), records


if __name__ == "__main__":
    run()

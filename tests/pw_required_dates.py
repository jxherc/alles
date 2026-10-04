"""Required dates are explained before submit and recover through the real picker."""

import base64
import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                zone = "America/Toronto" if theme == "light" else "Asia/Tokyo"
                options = dict(
                    timezone_id=zone,
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
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
                external, errors, console = [], [], []

                def route(request):
                    if urlparse(request.request.url).netloc != urlparse(base).netloc:
                        external.append(request.request.url)
                        return request.abort()
                    return request.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                row = {
                    "scenario_id": "forms.required-dates",
                    "profile": label,
                    "status": "failed",
                }
                rows.append(row)

                def capture(name):
                    screenshot = context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (output / f"{label}-{name}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )

                try:
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(base + "/api/settings", data={"timezone": ""}).ok
                    posts = []
                    page.on(
                        "request",
                        lambda r: (
                            posts.append(r.url)
                            if r.method == "POST"
                            and urlparse(r.url).path in ("/api/reminders", "/api/subscriptions")
                            else None
                        ),
                    )
                    page.goto(base + "/?view=reminders", wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    text = page.locator("#reminder-text")
                    time = page.locator("#reminder-time")
                    add = page.locator("#reminder-add-btn")
                    expect(page.locator("#reminder-required")).to_be_visible()
                    expect(time).to_have_attribute("aria-describedby", "reminder-required")
                    capture("reminder-empty")
                    add.press("Enter")
                    expect(text).to_be_focused()
                    name = f"synthetic reminder {label}"
                    text.fill(name)
                    add.press("Enter")
                    expect(time).to_be_focused()
                    expect(text).to_have_value(name)
                    expect(page.locator("#reminder-status")).to_contain_text(
                        "pick a valid date and time"
                    )
                    assert not posts, posts
                    time.press("Enter")
                    page.locator('.dp-nav[data-nav="-1"]').press("Enter")
                    page.locator('.dp-day[data-d="1"]').press("Enter")
                    page.keyboard.press("Escape")
                    add.press("Enter")
                    expect(time).to_be_focused()
                    expect(page.locator("#reminder-status")).to_contain_text("pick a future time")
                    assert not posts, posts
                    time.press("Enter")
                    for _ in range(2):
                        page.locator('.dp-nav[data-nav="1"]').press("Enter")
                    page.locator('.dp-day[data-d="1"]').press("Enter")
                    page.keyboard.press("Escape")
                    expect(time).to_be_focused()
                    chosen = time.evaluate("el=>el.value")
                    add.press("Enter")
                    expect(page.locator("#reminder-list")).to_contain_text(name)
                    saved = [
                        r for r in api.get(base + "/api/reminders").json() if r["text"] == name
                    ]
                    assert len(saved) == 1 and len(posts) == 1, (saved, posts)
                    stored_time = datetime.fromisoformat(
                        saved[0]["trigger_at"].replace("Z", "+00:00")
                    )
                    if stored_time.tzinfo is None:
                        stored_time = stored_time.replace(tzinfo=UTC)
                    assert (
                        stored_time.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%dT%H:%M") == chosen
                    )

                    page.reload(wait_until="networkidle")
                    expect(page.locator("#reminder-list")).to_contain_text(name)
                    assert [
                        r for r in api.get(base + "/api/reminders").json() if r["text"] == name
                    ] == saved
                    capture("reminder-saved")
                    page.goto(base + "/?view=subs", wait_until="networkidle")
                    name_field = page.locator("#sub-name")
                    due = page.locator("#sub-due")
                    add_sub = page.locator("#sub-add-btn")
                    expect(page.locator("#sub-required")).to_be_visible()
                    expect(due).to_have_attribute("aria-describedby", "sub-required")
                    capture("subscription-empty")
                    add_sub.press("Enter")
                    expect(name_field).to_be_focused()
                    subscription = f"synthetic renewal {label}"
                    name_field.fill(subscription)
                    page.locator("#sub-price").fill("12.5")
                    add_sub.press("Enter")
                    expect(due).to_be_focused()
                    expect(name_field).to_have_value(subscription)
                    expect(page.locator("#sub-price")).to_have_value("12.5")
                    assert len(posts) == 1, posts
                    due.press("Enter")
                    page.locator('.dp-nav[data-nav="1"]').press("Enter")
                    page.locator('.dp-day[data-d="1"]').press("Enter")
                    expect(due).to_be_focused()
                    billing = due.evaluate("el=>el.value")
                    page.locator("#sub-price").fill("invalid")
                    add_sub.press("Enter")
                    expect(page.locator("#sub-price")).to_be_focused()
                    assert len(posts) == 1, posts
                    page.locator("#sub-price").fill("12.5")
                    add_sub.press("Enter")
                    item = page.locator(".sub-item").filter(has_text=subscription)
                    expect(item).to_have_count(1)
                    expect(item).to_be_visible()
                    saved_sub = [
                        r
                        for r in api.get(base + "/api/subscriptions?advance=false").json()[
                            "subscriptions"
                        ]
                        if r["name"] == subscription
                    ]
                    assert len(saved_sub) == 1 and len(posts) == 2, (saved_sub, posts)
                    assert saved_sub[0]["next_due"] == billing and saved_sub[0]["price"] == 12.5
                    page.reload(wait_until="networkidle")
                    expect(item).to_have_count(1)
                    expect(item).to_be_visible()
                    current = [
                        r
                        for r in api.get(base + "/api/subscriptions?advance=false").json()[
                            "subscriptions"
                        ]
                        if r["name"] == subscription
                    ]
                    assert (
                        current[0]["id"] == saved_sub[0]["id"] and current[0]["next_due"] == billing
                    )
                    capture("subscription-saved")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        timezone=zone,
                        reminder_wall=chosen,
                        reminder_saved=saved[0]["trigger_at"],
                        billing_date=billing,
                        checks="visible required guidance, missing/invalid field focus, retained draft, no writes on invalid input, keyboard custom date picker, actual creation and reload, no duplicates, console and overflow",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
                    row.update(
                        page_errors=errors, console_errors=console, blocked_external=external
                    )
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()

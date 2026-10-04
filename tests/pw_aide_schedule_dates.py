"""Verify saved schedule dates remain recognizable without reopening the editor."""

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 390, 320] for t in ["light", "dark"]] + [
    (1440, t, True) for t in ["light", "dark"]
]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                timezone_id="UTC",
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / f"zoom-{theme}"
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
            external, errors, console, requests = [], [], [], []
            reject = False

            def route(r):
                url = urlparse(r.request.url)
                if url.netloc != urlparse(base).netloc:
                    external.append(r.request.url)
                    return r.abort()
                if url.path == "/api/jarvis/aide-schedules" and r.request.method == "POST":
                    requests.append(r.request.post_data_json)
                    if reject:
                        return r.fulfill(status=503, json={"detail": "owned save failed"})
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            zone = "America/Toronto" if theme == "dark" else "Pacific/Kiritimati"
            assert api.patch(base + "/api/settings", data={"timezone": zone}).ok
            page.goto(base + "/?app=scheduled", wait_until="networkidle")
            if zoom:
                worker = (
                    context.service_workers[0]
                    if context.service_workers
                    else context.wait_for_event("serviceworker")
                )
                assert (
                    worker.evaluate(
                        "async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",
                        base,
                    )
                    == 2
                )
                page.wait_for_function(
                    "innerWidth===720 && innerHeight===450 && devicePixelRatio===2"
                )
            for offset in [0, 1]:
                year = datetime.now(timezone.utc).year + 1 + offset
                value = f"{year}-12-31 23:59"
                name = f"owned year {label} {offset}"
                page.get_by_role("button", name="new schedule", exact=True).click()
                page.locator("#aide-schedule-name").fill(name)
                page.locator("#aide-schedule-prompt").fill("review synthetic local tasks")
                page.locator("[data-schedule-kind=once]").press("Space")
                page.locator("#aide-schedule-value").fill(value)
                if offset == 0:
                    reject = True
                    page.get_by_role("button", name="save schedule", exact=True).press("Enter")
                    expect(page.locator("#aide-schedule-form-status")).to_have_text(
                        "owned save failed"
                    )
                    expect(page.locator("#aide-schedule-name")).to_have_value(name)
                    expect(page.locator("#aide-schedule-value")).to_have_value(value)
                    reject = False
                page.get_by_role("button", name="save schedule", exact=True).press("Enter")
                row = page.locator(".aide-schedule-row").filter(has_text=name)
                expect(row).to_be_visible()
                page.reload(wait_until="networkidle")
                expect(row).to_be_visible()
                spans = row.locator(".aide-schedule-meta > span").all_text_contents()
                rows.append(
                    {
                        "profile": label,
                        "year": year,
                        "date": value,
                        "timezone": zone,
                        "summary": spans,
                        "year_in_schedule": str(year) in spans[0],
                        "year_in_next": str(year) in spans[2],
                        "wall_matches_next": spans[0].removeprefix("once · ")
                        == spans[2].removeprefix("next "),
                    }
                )
                (out / "observations.json").write_text(json.dumps(rows, indent=2))
                row.scroll_into_view_if_needed()
                shot = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{offset}-saved.png").write_bytes(base64.b64decode(shot["data"]))
                row.get_by_role("button", name="edit", exact=True).press("Enter")
                expect(page.locator("#aide-schedule-value")).to_have_value(value)
                expect(page.locator("#aide-schedule-name")).to_have_value(name)
                page.get_by_role("button", name="cancel", exact=True).press("Enter")
                row.get_by_role("button", name="pause", exact=True).press("Enter")
                expect(row.locator(".aide-schedule-state")).to_have_text("paused")
                page.reload(wait_until="networkidle")
                expect(row.locator(".aide-schedule-state")).to_have_text("paused")
                row.get_by_role("button", name="edit", exact=True).press("Enter")
                expect(page.locator("#aide-schedule-value")).to_have_value(value)
                page.get_by_role("button", name="cancel", exact=True).press("Enter")
            assert len(requests) == 3 and all(r["timezone"] == zone for r in requests), requests
            assert not errors and not external, (errors, external)
            assert console == [
                "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            ], console
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            with (out / "console.jsonl").open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "profile": label,
                            "errors": errors,
                            "console": console,
                            "expected": "one synthetic refused save",
                        }
                    )
                    + "\n"
                )
            context.close()
    finally:
        browser.close()
assert all(r["year_in_schedule"] and r["year_in_next"] and r["wall_matches_next"] for r in rows), (
    rows
)
(out / "scenarios.json").write_text(
    json.dumps(
        [
            {
                "scenario_id": "aide.schedule-dates",
                "profile": f"{w}-{t}" + ("-native200" if z else ""),
                "status": "passed",
                "checks": "adjacent future-year summaries, exact dates and zone, save rejection/draft retention/retry, pause/reload/edit, keyboard, native zoom",
            }
            for w, t, z in profiles
        ],
        indent=2,
    )
)

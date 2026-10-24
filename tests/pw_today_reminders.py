"""Home reminder day/clock and navigation using the real API and browser.

Only the browser clock/timezone is simulated. Future synthetic reminder fixtures avoid
being consumed by the live scheduler. No response or UI event is manufactured.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section

CASES = (
    {
        "name": "toronto-after-utc-midnight",
        "browser_zone": "America/Toronto",
        "configured_zone": "",
        "zone": "America/Toronto",
        "now": "2032-09-26T01:00:00+00:00",
        "day": "2032-09-25",
        "trigger": "2032-09-26T00:30:00",
        "clock": "20:30",
        "future": "2032-09-26T04:00:00",
        "earlier": "2032-09-24T23:00:00",
        "earlier_lines": r"Sep 24\n7:00\sPM",
        "earlier_title": r"Sep 24, 2032, 7:00\sPM",
    },
    {
        "name": "tokyo-before-utc-midnight",
        "browser_zone": "Asia/Tokyo",
        "configured_zone": "",
        "zone": "Asia/Tokyo",
        "now": "2032-09-25T16:00:00+00:00",
        "day": "2032-09-26",
        "trigger": "2032-09-25T15:30:00",
        "clock": "00:30",
        "future": "2032-09-26T15:00:00",
        "earlier": "2032-09-25T01:00:00",
        "earlier_lines": r"Sep 25\n10:00\sAM",
        "earlier_title": r"Sep 25, 2032, 10:00\sAM",
    },
    {
        "name": "configured-zone-overrides-browser",
        "browser_zone": "America/Toronto",
        "configured_zone": "Asia/Tokyo",
        "zone": "Asia/Tokyo",
        "now": "2032-09-25T16:00:00+00:00",
        "day": "2032-09-26",
        "trigger": "2032-09-25T15:30:00",
        "clock": "00:30",
        "future": "2032-09-26T15:00:00",
        "earlier": "2032-09-25T01:00:00",
        "earlier_lines": r"Sep 25\n10:00\sAM",
        "earlier_title": r"Sep 25, 2032, 10:00\sAM",
    },
)


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            record = {
                "scenario_id": "home.reminder-local-time",
                "feature_id": "home.capture-and-navigation",
                "profile": profile,
                "status": "failed",
                "detail": "workflow did not finish",
                "simulation": "browser clock/timezone only; fixtures and responses use real API",
                "cases": [],
            }
            records.append(record)
            for case in CASES:
                label = f"{profile}-{case['name']}"
                context = browser.new_context(
                    viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                    is_mobile=profile == "phone",
                    has_touch=profile == "phone",
                    reduced_motion="reduce",
                    locale="en-US",
                    timezone_id=case["browser_zone"],
                    service_workers="block",
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.set_default_timeout(15000)
                page.clock.set_fixed_time(datetime.fromisoformat(case["now"]))
                events = {
                    "console": [],
                    "page_errors": [],
                    "failed_requests": [],
                    "http_errors": [],
                    "today_requests": [],
                }
                page.on(
                    "console",
                    lambda msg: events["console"].append({"type": msg.type, "text": msg.text}),
                )
                page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: events["failed_requests"].append(
                        {"url": request.url, "failure": request.failure}
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        events["http_errors"].append(
                            {"url": response.url, "status": response.status}
                        )
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        events["today_requests"].append(request.url)
                        if urlsplit(request.url).path == "/api/today"
                        else None
                    ),
                )
                ids = []
                visible = f"call 家人 {label}"
                future = f"tomorrow {label}"
                earlier = f"left over {label}"
                try:
                    settings = context.request.patch(
                        base + "/api/settings", data={"timezone": case["configured_zone"]}
                    )
                    assert settings.ok, settings.text()
                    for text, trigger in (
                        (visible, case["trigger"]),
                        (future, case["future"]),
                        (earlier, case["earlier"]),
                    ):
                        seeded = context.request.post(
                            base + "/api/reminders", data={"text": text, "trigger_at": trigger}
                        )
                        assert seeded.ok, seeded.text()
                        ids.append(seeded.json()["id"])
                    page.goto(base + "/?view=today", wait_until="networkidle")
                    if page.locator("#setup-skip").is_visible():
                        page.locator("#setup-skip").click()
                    if profile == "phone":
                        page.locator("#today-settings").click()
                        choose_settings_section(page, "themes")
                        with page.expect_response(
                            lambda response: (
                                response.url.endswith("/api/appearance")
                                and response.request.method == "PUT"
                            )
                        ) as appearance:
                            page.locator('[data-theme-mode="light"]').click()
                        assert appearance.value.ok
                        page.locator("#settings-modal-close").click()
                    row = page.locator(".today-schedule .today-row").filter(has_text=visible)
                    expect(row).to_be_visible()
                    # the server's wall clock, read in the app's own short time style
                    clock = page.evaluate(
                        "async c => (await import('/static/js/i18n.js')).formatClock(c)",
                        case["clock"],
                    )
                    assert clock and clock != "", clock
                    expect(row.locator("em")).to_have_text(clock)
                    expect(page.locator(".today-schedule")).not_to_contain_text(future)
                    # one left over from an earlier local day says which day: day over time in
                    # the narrow column, the reminders list's full text on hover
                    leftover = page.locator(".today-schedule .today-row").filter(has_text=earlier)
                    expect(leftover.locator("em")).to_have_text(
                        re.compile(f"^{case['earlier_lines']}$"), use_inner_text=True
                    )
                    expect(leftover.locator("em")).to_have_attribute(
                        "title", re.compile(f"^{case['earlier_title']}$")
                    )
                    meta, title = (leftover.locator(sel).bounding_box() for sel in ("em", "b"))
                    assert meta["x"] + meta["width"] <= title["x"], (meta, title)
                    assert events["today_requests"], events
                    for url in events["today_requests"]:
                        params = parse_qs(urlsplit(url).query)
                        assert params.get("date") == [case["day"]], params
                        assert params.get("timezone") == [case["zone"]], params
                    page.reload(wait_until="networkidle")
                    expect(row.locator("em")).to_have_text(clock)
                    expect(page.locator(".today-schedule")).not_to_contain_text(future)
                    saved = context.request.get(base + "/api/reminders").json()
                    assert {r["id"]: r["trigger_at"] for r in saved if r["id"] in ids} == dict(
                        zip(ids, (case["trigger"], case["future"], case["earlier"]), strict=True)
                    )
                    row.click()
                    expect(page.locator("#plan-view")).to_be_visible()
                    page.go_back(wait_until="networkidle")
                    expect(row).to_be_visible()
                    page.locator("#today-capture-input").click()
                    for _ in range(30):
                        page.keyboard.press("Tab")
                        if row.evaluate("element => element === document.activeElement"):
                            break
                    expect(row).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(page.locator("#plan-view")).to_be_visible()
                    page.go_back(wait_until="networkidle")
                    expect(row.locator("em")).to_have_text(clock)
                    expect(page.locator(".today-schedule")).not_to_contain_text(future)
                    expect(row).to_be_visible()
                    box = page.wait_for_function(
                        """text => {
                      const element = [...document.querySelectorAll('.today-schedule .today-row')]
                        .find(node => node.textContent.includes(text));
                      const rect = element?.getBoundingClientRect();
                      return rect && rect.width >= 44 && rect.height >= 44
                        ? {x:rect.x,y:rect.y,width:rect.width,height:rect.height} : false;
                    }""",
                        arg=visible,
                    ).json_value()
                    assert box and box["width"] >= 44 and box["height"] >= 44, box
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    page.screenshot(path=str(output / f"{label}.png"), full_page=True)
                    assert not events["page_errors"], events
                    assert not events["http_errors"], events
                    assert not events["failed_requests"], events
                    assert not [e for e in events["console"] if e["type"] == "error"], events
                    record["cases"].append(
                        {"name": case["name"], "status": "passed", "screenshot": f"{label}.png"}
                    )
                except Exception:
                    page.screenshot(path=str(output / f"{label}-failure.png"), full_page=True)
                    raise
                finally:
                    (output / f"{label}-events.json").write_text(json.dumps(events, indent=2))
                    (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                    for reminder_id in ids:
                        context.request.delete(base + f"/api/reminders/{reminder_id}")
                    context.tracing.stop(path=str(output / f"{label}-trace.zip"))
                    context.close()
            record.update(
                status="passed",
                detail="local day and clock, next-day exclusion, reload, pointer and keyboard navigation",
            )
            (output / "scenarios.json").write_text(json.dumps(records, indent=2))
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()

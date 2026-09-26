"""Calendar optional metadata recovery and narrow/zoomed shared date picker."""

from __future__ import annotations

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"])
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in [320, 360, 390, 1440]:
            profile = f"width-{width}"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                timezone_id="America/Toronto",
                reduced_motion="reduce",
                service_workers="block",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            events, allowed = [], set()
            page.on("pageerror", lambda error: events.append({"pageerror": str(error)}))
            page.on(
                "console",
                lambda message: events.append(
                    {
                        "console": message.type,
                        "text": message.text,
                        "url": message.location.get("url", ""),
                    }
                ),
            )
            page.on(
                "requestfailed",
                lambda request: events.append({"failed": request.url, "reason": request.failure}),
            )
            page.on(
                "response",
                lambda response: (
                    events.append({"status": response.status, "url": response.url})
                    if response.status >= 400
                    else None
                ),
            )
            active = None

            def begin(name):
                nonlocal active
                active = {"scenario_id": f"calendar.{name}", "profile": profile, "status": "failed"}
                records.append(active)

            def passed(**proof):
                active.update(status="passed", **proof)

            def snapshot(name):
                page.screenshot(path=str(out / f"{profile}-{name}.png"), full_page=True)

            def calendar():
                page.get_by_role("tab", name="calendar", exact=True).click()
                months = "January February March April May June July August September October November December".split()
                for _ in range(120):
                    if page.locator("#cal-load-error").is_visible():
                        return
                    month, year = page.locator("#cal-month-label").inner_text().split()
                    n = int(year) * 12 + months.index(month)
                    target = 2026 * 12 + 8
                    if n == target:
                        return
                    page.locator("#cal-next" if n < target else "#cal-prev").click()
                raise AssertionError("fixture month unavailable")

            def fail(route):
                allowed.add(route.request.url)
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"simulated metadata failure"}',
                )

            try:
                cal = context.request.post(
                    base + "/api/calendars", data={"name": profile + " research 研究"}
                ).json()
                event = context.request.post(
                    base + "/api/calendar",
                    data={
                        "title": profile + " kept event",
                        "calendar_id": cal["id"],
                        "start_dt": "2026-09-25T09:00",
                        "end_dt": "2026-09-25T10:00",
                    },
                ).json()
                page.route("**/api/calendars", fail)
                page.goto(base + "/?view=plan", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                calendar()
                begin("optional-metadata-retains-events-and-id")
                expect(page.locator("#cal-metadata-error")).to_be_visible()
                expect(page.locator("#cal-load-error")).to_have_count(0)
                page.locator(f'.cal-chip[data-id="{event["id"]}"]').click()
                expect(page.locator("#cal-calendar")).to_have_attribute("aria-disabled", "true")
                expect(page.locator("#cal-calendar")).to_have_attribute("data-value", cal["id"])
                page.locator("#cal-desc").fill("Description saved without metadata")
                page.locator("#cal-save").click()
                expect(page.locator("#cal-title")).to_have_count(0)
                current = next(
                    e
                    for e in context.request.get(base + "/api/calendar").json()
                    if e["id"] == event["id"]
                )
                assert (
                    current["calendar_id"] == cal["id"]
                    and current["description"] == "Description saved without metadata"
                )
                snapshot("metadata-failure-events-kept")
                page.unroute("**/api/calendars", fail)
                page.locator("#cal-metadata-error").get_by_role("button", name="retry").click()
                expect(page.locator("#cal-metadata-error")).to_have_count(0)
                expect(page.locator("#plan-view > .specialist-state")).to_be_hidden()
                page.reload(wait_until="networkidle")
                calendar()
                saved = next(
                    e
                    for e in context.request.get(base + "/api/calendar").json()
                    if e["id"] == event["id"]
                )
                assert saved == current
                passed(saved=saved)

                begin("metadata-retry-preserves-draft")
                page.route("**/api/calendars", fail)
                page.get_by_role("tab", name="tasks", exact=True).click()
                calendar()
                expect(page.locator("#cal-metadata-error")).to_be_visible()
                expect(page.locator(".cal-cal-name").filter(has_text=cal["name"])).to_have_count(1)
                page.locator(f'.cal-chip[data-id="{event["id"]}"]').click()
                page.locator("#cal-desc").fill("Unsaved metadata retry draft")
                before = context.request.get(base + "/api/calendar").json()
                page.unroute("**/api/calendars", fail)
                page.locator("#cal-metadata-error").get_by_role("button", name="retry").click()
                expect(page.locator("#cal-metadata-error")).to_have_count(0)
                expect(page.locator("#cal-desc")).to_have_value("Unsaved metadata retry draft")
                expect(page.locator("#cal-calendar")).to_have_attribute("data-value", cal["id"])
                expect(page.locator("#cal-calendar")).to_have_attribute("aria-disabled", "false")
                expect(page.locator("#plan-view > .specialist-state")).to_be_hidden()
                assert context.request.get(base + "/api/calendar").json() == before
                page.locator("#cal-save").click()
                expect(page.locator("#cal-title")).to_have_count(0)
                page.reload(wait_until="networkidle")
                calendar()
                saved = next(
                    e
                    for e in context.request.get(base + "/api/calendar").json()
                    if e["id"] == event["id"]
                )
                assert (
                    saved["description"] == "Unsaved metadata retry draft"
                    and saved["calendar_id"] == cal["id"]
                )
                passed(saved=saved)

                begin("calendar-retry-refreshes-owner-state")
                page.route("**/api/calendar", fail)
                page.reload(wait_until="networkidle")
                calendar()
                expect(page.locator("#cal-load-error")).to_be_visible()
                expect(page.locator("#plan-view > .specialist-state")).to_be_visible()
                page.unroute("**/api/calendar", fail)
                page.route("**/api/calendar/tasks", fail)
                page.locator("#cal-load-error").get_by_role("button", name="retry").click()
                expect(page.locator("#cal-load-error")).to_have_count(0)
                expect(page.locator("#plan-view > .specialist-state")).to_be_visible()
                expect(page.locator("#plan-view > .specialist-state")).to_have_attribute(
                    "data-state", "partial"
                )
                snapshot("unrelated-failure-retained")
                page.unroute("**/api/calendar/tasks", fail)
                page.locator("#plan-view > .specialist-state").get_by_role(
                    "button", name="retry"
                ).click()
                expect(page.locator("#plan-view > .specialist-state")).to_be_hidden()
                page.route("**/api/calendar", fail)
                page.reload(wait_until="networkidle")
                calendar()
                page.unroute("**/api/calendar", fail)
                page.locator("#cal-load-error").get_by_role("button", name="retry").click()
                expect(page.locator("#plan-view > .specialist-state")).to_be_hidden()
                expect(page.locator(f'.cal-chip[data-id="{event["id"]}"]')).to_be_visible()
                passed()

                begin("narrow-picker-seven-columns-and-focus")
                page.locator("#cal-new-btn").click()
                page.locator("#cal-title").click()
                for _ in range(60):
                    page.keyboard.press("Tab")
                    if page.locator("#cal-end").evaluate("e=>e===document.activeElement"):
                        break
                else:
                    raise AssertionError("end picker not keyboard reachable")
                page.keyboard.press("Enter")
                panel = page.locator(".date-panel")
                expect(panel).to_be_visible()
                if width == 1440:
                    context.new_cdp_session(page).send(
                        "Emulation.setPageScaleFactor", {"pageScaleFactor": 2}
                    )
                    page.wait_for_timeout(150)
                geometry = panel.evaluate(
                    'e=>({client:e.clientWidth,scroll:e.scrollWidth,panel:e.getBoundingClientRect().toJSON(),viewport:{left:visualViewport.offsetLeft,top:visualViewport.offsetTop,width:visualViewport.width,height:visualViewport.height,scale:visualViewport.scale},days:[...e.querySelectorAll(".dp-day")].map(b=>({day:b.dataset.d,...b.getBoundingClientRect().toJSON()}))})'
                )
                assert geometry["scroll"] <= geometry["client"], geometry
                viewport = geometry["viewport"]
                for day in geometry["days"]:
                    assert day["width"] >= 44 and day["height"] >= 44, day
                    assert (
                        day["left"] >= viewport["left"]
                        and day["right"] <= viewport["left"] + viewport["width"] + 1
                    ), day
                for day in range(20, 27):
                    panel.locator(f'.dp-day[data-d="{day}"]').click()
                    assert page.locator("#cal-end").get_attribute("data-value")[8:10] == str(day)
                for _ in range(panel.locator("button").count() + 2):
                    page.keyboard.press("Tab")
                    assert panel.evaluate("e=>e.contains(document.activeElement)")
                snapshot("picker")
                page.keyboard.press("Escape")
                expect(page.locator("#cal-end")).to_be_focused()
                passed(
                    geometry=geometry,
                    zoom="200% visual viewport scale" if width == 1440 else "100%",
                )
                assert not [e for e in events if "pageerror" in e or "failed" in e], events
                assert not [
                    e
                    for e in events
                    if e.get("status", 0) >= 400 and (e["url"] not in allowed or e["status"] != 503)
                ], events
                assert not [
                    e
                    for e in events
                    if e.get("console") == "error"
                    and (
                        e["url"] not in allowed
                        or e["text"]
                        != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                    )
                ], events
            except Exception as error:
                if active:
                    active.update(status="failed", error=str(error))
                snapshot("failure")
                raise
            finally:
                (out / "scenarios.json").write_text(json.dumps(records, indent=2))
                (out / f"{profile}-events.json").write_text(json.dumps(events, indent=2))
                context.tracing.stop(path=str(out / f"{profile}.zip"))
                context.close()
        browser.close()
    print(json.dumps({"passed": len(records)}))


if __name__ == "__main__":
    run()

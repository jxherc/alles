"""4a - contact birthdays show as a yearly all-day overlay on the calendar: the month cell (or its
"+N more" when a phone cell is too short), the same day a year later, and the week and day
all-day rows.

Runs against an owned throwaway server like the other gates: PORT, ALLES_TEST_RUN_ID and
ALLES_BROWSER_ARTIFACTS come from the gate runner.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

NAME = "Grace Hopper"
MONTHS = "January February March April May June July August September October November December"
PROFILES = (
    ("desktop", {"width": 1440, "height": 900}, False),
    ("tablet", {"width": 820, "height": 1180}, True),
    ("phone", {"width": 390, "height": 844}, True),
)


def fixture_day():
    # the 15th of next month: always a full month away from any edge of the current one
    return (date.today().replace(day=1) + timedelta(days=32)).replace(day=15)


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"]) / "calendar-birthdays"
    output.mkdir(parents=True, exist_ok=True)
    day = fixture_day()
    records = []
    with sync_playwright() as p:
        api = p.request.new_context()
        assert api.post(base + "/api/setup/dismiss").ok
        made = api.post(
            base + "/api/contacts", data={"name": NAME, "birthday": f"1990-{day:%m-%d}"}
        )
        assert made.ok, made.text()
        cid = made.json()["id"]
        browser = p.chromium.launch()
        try:
            for profile, viewport, touch in PROFILES:
                record = {"scenario_id": "calendar.contact-birthdays", "profile": profile}
                record["status"] = "failed"
                records.append(record)
                context = browser.new_context(
                    viewport=viewport,
                    is_mobile=touch,
                    has_touch=touch,
                    timezone_id="America/Toronto",
                    locale="en-US",
                    reduced_motion="reduce",
                    service_workers="block",
                )
                page = context.new_page()
                page.set_default_timeout(12000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda msg: errors.append(msg.text) if msg.type == "error" else None,
                )
                page.on(
                    "response",
                    lambda res: (
                        errors.append(f"{res.status} {res.url}") if res.status >= 400 else None
                    ),
                )
                try:
                    page.goto(base + "/?view=calendar", wait_until="networkidle")
                    expect(page.locator("#calendar-view")).to_be_visible()
                    pick_view(page, "month")
                    later = day.replace(year=day.year + 1)
                    # a year later first, so the week and day views start next to the fixture
                    record["month"] = {
                        str(when): month(page, when, profile, output) for when in (later, day)
                    }
                    for view in ("week", "day"):
                        time_grid(page, view, day, profile, output)
                    assert not errors, errors
                    record["status"] = "passed"
                except Exception:
                    page.screenshot(path=str(output / f"{profile}-failure.png"), full_page=True)
                    record["errors"] = errors
                    raise
                finally:
                    (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                    context.close()
        finally:
            browser.close()
            api.delete(base + f"/api/contacts/{cid}")
            api.dispose()
    print(json.dumps({"status": "passed", "scenarios": records}))


def pick_view(page, name):
    button = page.locator(f'#cal-view .seg-opt[data-view="{name}"]')
    if button.get_attribute("aria-pressed") != "true":
        button.click()
    expect(button).to_have_attribute("aria-pressed", "true")


def go_to_month(page, when):
    names = MONTHS.split()
    target = when.year * 12 + when.month - 1
    for _ in range(40):
        name, year = page.locator("#cal-month-label").inner_text().split()
        current = int(year) * 12 + names.index(name)
        if current == target:
            return
        page.locator("#cal-next" if current < target else "#cal-prev").click()
    raise AssertionError("fixture month was not reachable")


def month(page, when, profile, output):
    go_to_month(page, when)
    # the month trims lines a frame after it draws; read it once that's done
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    cell = page.locator(f'.cal-cell[data-date="{when}"]')
    expect(cell).to_be_visible()
    bday = cell.locator(".cal-bday")
    if bday.count():
        expect(bday).to_have_text(NAME)
        # the cake is the app's own svg icon, never an emoji
        expect(bday.locator("svg")).to_have_count(1)
        shown = "line"
    else:
        # a phone cell can be too short for even one line; then "+1 more" stands in for it
        # (it reads "+1" in a narrow cell; its name is "1 more" either way)
        expect(cell.locator(".cal-more")).to_have_attribute("aria-label", "1 more")
        shown = "more"
    expect(page.locator(".cal-cell", has_text=NAME)).to_have_count(1 if shown == "line" else 0)
    if profile == "desktop":
        assert shown == "line", shown
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    page.screenshot(path=str(output / f"{profile}-month-{when}.png"), full_page=True)
    if shown == "more":
        cell.locator(".cal-more").click()
        expect(page.locator(f'.cal-tg-allday[data-date="{when}"] .cal-bday')).to_have_text(NAME)
        pick_view(page, "month")
    return shown


def time_grid(page, view, when, profile, output):
    pick_view(page, view)
    key = str(when)
    for _ in range(80):
        keys = [s.get_attribute("data-date") for s in page.locator(".cal-tg-allday").all()]
        if key in keys:
            break
        page.locator("#cal-next" if keys[-1] < key else "#cal-prev").click()
    else:
        raise AssertionError(f"birthday not reachable in the {view} view")
    expect(page.locator(f'.cal-tg-allday[data-date="{key}"] .cal-bday')).to_have_text(NAME)
    expect(page.locator(".cal-tg-allday .cal-bday")).to_have_count(1)
    page.screenshot(path=str(output / f"{profile}-{view}.png"), full_page=True)


if __name__ == "__main__":
    run()

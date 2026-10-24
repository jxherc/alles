"""A multi-day all-day event shows on every day it spans: in the month cells (or behind a cell's
"+N more" when a phone cell is too short), and as a 44px button in the week and day all-day rows
that opens the event by pointer and keyboard.

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

TITLE = "MULTIDAY_TRIP"
MONTHS = "January February March April May June July August September October November December"
PROFILES = (
    ("desktop", {"width": 1440, "height": 900}, False),
    ("tablet", {"width": 820, "height": 1180}, True),
    ("phone", {"width": 390, "height": 844}, True),
)


def fixture_days():
    # the first saturday of next month to the monday after, so the trip crosses a week row in
    # the month and spills into a second week. no fake browser clock: it swaps out Date, and
    # the calendar's wall-date subclass of Date stops being one
    first = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    sat = first + timedelta(days=(5 - first.weekday()) % 7)
    span = tuple((sat + timedelta(days=n)).isoformat() for n in range(3))
    outside = ((sat - timedelta(days=1)).isoformat(), (sat + timedelta(days=3)).isoformat())
    return sat, span, outside


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"]) / "calendar-multiday"
    output.mkdir(parents=True, exist_ok=True)
    sat, span, outside = fixture_days()
    records = []
    with sync_playwright() as p:
        api = p.request.new_context()
        assert api.post(base + "/api/setup/dismiss").ok
        made = api.post(
            base + "/api/calendar",
            data={"title": TITLE, "start_dt": span[0], "end_dt": span[-1], "all_day": True},
        )
        assert made.ok, made.text()
        eid = made.json()["id"]
        browser = p.chromium.launch()
        try:
            for profile, viewport, touch in PROFILES:
                record = {"scenario_id": "calendar.multiday-all-day", "profile": profile}
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
                    record["month"] = month(page, eid, sat, span, outside, profile, output)
                    record["week"] = week(page, eid, span, output, profile)
                    day(page, eid, span[1], output, profile)
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
            api.delete(base + f"/api/calendar/{eid}")
            api.dispose()
    print(json.dumps({"status": "passed", "scenarios": records}))


def settle(page):
    # the month trims lines a frame after it draws; read it once that's done
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


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


def opens_editor(page, trigger, *, keyboard=False):
    if keyboard:
        trigger.focus()
        page.keyboard.press("Enter")
    else:
        trigger.click()
    expect(page.locator("#cal-title")).to_have_value(TITLE)
    page.locator("#cal-back").click()
    expect(page.locator("#cal-title")).to_have_count(0)
    assert page.evaluate("document.activeElement !== document.body"), "focus fell to body"


def tap_size(locator):
    box = locator.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44, box


def month(page, eid, sat, span, outside, profile, output):
    pick_view(page, "month")
    go_to_month(page, sat)
    settle(page)
    shown = {}
    for key in span:
        cell = page.locator(f'.cal-cell[data-date="{key}"]')
        chip = cell.locator(f'.cal-chip[data-id="{eid}"]')
        if chip.count():
            expect(chip).to_be_visible()
            expect(chip).to_have_text(TITLE)
            shown[key] = "chip"
        else:
            # a phone cell can be too short for even one line; then "+1 more" stands in for it
            # (it reads "+1" in a narrow cell; its name is "1 more" either way)
            expect(cell.locator(".cal-more")).to_have_attribute("aria-label", "1 more")
            shown[key] = "more"
    for key in outside:
        cell = page.locator(f'.cal-cell[data-date="{key}"]')
        expect(cell.locator(f'.cal-chip[data-id="{eid}"]')).to_have_count(0)
        expect(cell.locator(".cal-more")).to_have_count(0)
    if profile == "desktop":
        assert set(shown.values()) == {"chip"}, shown
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    page.screenshot(path=str(output / f"{profile}-month.png"), full_page=True)
    first = page.locator(f'.cal-cell[data-date="{span[0]}"]')
    if shown[span[0]] == "chip":
        opens_editor(page, first.locator(f'.cal-chip[data-id="{eid}"]'))
    else:
        # "+N more" opens that day with focus on its first all-day item: the trip
        first.locator(".cal-more").click()
        expect(page.locator('#cal-view .seg-opt[data-view="day"]')).to_have_attribute(
            "aria-pressed", "true"
        )
        found = page.locator(f'.cal-tg-allday[data-date="{span[0]}"] .cal-allday-ev')
        expect(found).to_have_attribute("data-id", eid)
        expect(found).to_be_focused()
    return shown


def shown_days(page):
    return [
        slot.get_attribute("data-date") for slot in page.locator(".cal-tg-allday[data-date]").all()
    ]


def week(page, eid, span, output, profile):
    pick_view(page, "week")
    seen = set()
    for _ in range(12):
        keys = shown_days(page)
        if keys[0] > span[0] and not seen:
            page.locator("#cal-prev").click()
            continue
        for key in keys:
            button = page.locator(f'.cal-tg-allday[data-date="{key}"] .cal-allday-ev')
            if key in span:
                # the later days count too: the trip began in the week before
                expect(button, f"{TITLE} missing from the all-day row on {key}").to_have_count(1)
                expect(button).to_have_attribute("data-id", eid)
                expect(button).to_have_text(TITLE)
                tap_size(button)
                seen.add(key)
            else:
                expect(button).to_have_count(0)
        if seen == set(span):
            break
        page.locator("#cal-next").click()
    assert seen == set(span), seen
    page.screenshot(path=str(output / f"{profile}-week.png"), full_page=True)
    return sorted(seen)


def day(page, eid, key, output, profile):
    pick_view(page, "day")
    for _ in range(40):
        shown = shown_days(page)[0]
        if shown == key:
            break
        page.locator("#cal-next" if shown < key else "#cal-prev").click()
    else:
        raise AssertionError("trip day not reachable in the day view")
    button = page.locator(f'.cal-tg-allday[data-date="{key}"] .cal-allday-ev[data-id="{eid}"]')
    expect(button).to_have_text(TITLE)
    tap_size(button)
    page.screenshot(path=str(output / f"{profile}-day.png"), full_page=True)
    opens_editor(page, button)
    opens_editor(page, button, keyboard=True)


if __name__ == "__main__":
    run()

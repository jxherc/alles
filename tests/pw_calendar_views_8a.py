"""8a UI verification: agenda + year views, working-hours shading, secondary tz, ICS feeds.

Runs against an owned throwaway server like the other gates: PORT, ALLES_TEST_RUN_ID and
ALLES_BROWSER_ARTIFACTS come from the gate runner.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")
# a loopback feed: the subscription is still saved and listed, and nothing leaves the machine
FEED = "http://127.0.0.1:9/holidays.ics"
# the browser's zone is pinned and quick add reads "today" there, whatever zone the runner has
ZONE = "America/Toronto"


def main():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    evid = Path(os.environ["ALLES_BROWSER_ARTIFACTS"]) / "calendar-views-8a"
    evid.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(
            viewport={"width": 1440, "height": 900}, service_workers="block", timezone_id=ZONE
        ).new_page()
        pg.set_default_timeout(12000)
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )
        api = pg.request
        assert api.post(base + "/api/setup/dismiss").ok

        # settings: secondary tz + working hours; seed two events
        assert api.patch(
            base + "/api/settings",
            data={"cal_secondary_tz": "Europe/London", "cal_work_start": 9, "cal_work_end": 17},
        ).ok
        for text in ("project review tomorrow 10am", "standup today 9am"):
            assert api.post(
                base + "/api/calendar/quick",
                data={"text": text},
                headers={"x-alles-time-zone": ZONE},
            ).ok

        pg.goto(base + "/?view=calendar", wait_until="networkidle")
        expect(pg.locator("#calendar-view")).to_be_visible()
        view = pg.locator("#cal-view")

        # ---- view buttons present ----
        r["agenda_year_buttons"] = (
            view.locator('[data-view="agenda"]').count() == 1
            and view.locator('[data-view="year"]').count() == 1
        )

        # ---- secondary tz world clock ----
        expect(pg.locator("#cal-worldclock")).to_be_visible()
        r["secondary_tz_shows"] = "London" in pg.locator("#cal-worldclock").inner_text()

        # ---- agenda view renders ----
        view.locator('[data-view="agenda"]').click()
        expect(pg.locator(".cal-agenda .cal-agenda-day").first).to_be_visible()
        r["agenda_view_renders"] = pg.locator(".cal-agenda-ev").count() >= 2
        pg.screenshot(path=str(evid / "agenda.png"))

        # ---- year view renders (12 months) ----
        view.locator('[data-view="year"]').click()
        expect(pg.locator(".cal-year .cal-year-month").first).to_be_visible()
        r["year_view_renders"] = pg.locator(".cal-year-month").count() == 12
        pg.screenshot(path=str(evid / "year.png"))

        # ---- working-hours shading in week view ----
        view.locator('[data-view="week"]').click()
        expect(pg.locator(".cal-tg-slot").first).to_be_visible()
        r["working_hours_shaded"] = pg.locator(".cal-tg-slot.offhours").count() > 0

        # ---- subscribe to an ICS feed via the UI (2 prompts) ----
        pg.locator("#cal-feed-add").click()
        pg.locator(".dialog-input").fill(FEED)
        pg.locator("[data-dialog-confirm]").click()
        expect(pg.locator(".dialog-input")).to_have_value("Subscription")
        pg.locator(".dialog-input").fill("Holidays")
        pg.locator("[data-dialog-confirm]").click()
        row = pg.locator(".cal-feed-row .cal-feed-name", has_text="Holidays")
        expect(row).to_be_visible()
        subs = api.get(base + "/api/calendar/subscriptions").json()
        r["subscription_add"] = any(s["url"] == FEED for s in subs)
        r["subscription_lists"] = row.count() == 1
        pg.screenshot(path=str(evid / "feeds.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (evid / "pw_calendar_views_8a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

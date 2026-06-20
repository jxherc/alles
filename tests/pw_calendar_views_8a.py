"""8a UI verification — agenda + year views, working-hours shading, secondary tz, ICS feeds.
calendar.localhost:8864.  ALLES_DATA=/tmp/alles8a PORT=8864 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CAL = "http://calendar.localhost:8864"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "8a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
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

        pg.goto(f"{CAL}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#calendar-view", timeout=15000)

        # settings: secondary tz + working hours; seed two events
        pg.evaluate(
            "() => fetch('/api/settings',{method:'PATCH',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({cal_secondary_tz:'Europe/London',cal_work_start:9,cal_work_end:17})})"
        )
        pg.evaluate(
            "() => fetch('/api/calendar/quick',{method:'POST',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({text:'project review tomorrow 10am'})})"
        )
        pg.evaluate(
            "() => fetch('/api/calendar/quick',{method:'POST',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({text:'standup today 9am'})})"
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#calendar-view", timeout=12000)
        pg.wait_for_timeout(600)

        # ---- view buttons present ----
        r["agenda_year_buttons"] = (
            pg.query_selector('.cal-view-btn[data-view="agenda"]') is not None
            and pg.query_selector('.cal-view-btn[data-view="year"]') is not None
        )

        # ---- secondary tz world clock ----
        r["secondary_tz_shows"] = pg.query_selector("#cal-worldclock") is not None

        # ---- agenda view renders ----
        pg.eval_on_selector('.cal-view-btn[data-view="agenda"]', "el => el.click()")
        pg.wait_for_selector(".cal-agenda .cal-agenda-day", timeout=8000)
        r["agenda_view_renders"] = pg.query_selector(".cal-agenda-ev") is not None
        pg.screenshot(path=str(EVID / "agenda.png"))

        # ---- year view renders (12 months) ----
        pg.eval_on_selector('.cal-view-btn[data-view="year"]', "el => el.click()")
        pg.wait_for_selector(".cal-year .cal-year-month", timeout=8000)
        months = pg.eval_on_selector_all(".cal-year-month", "els => els.length")
        r["year_view_renders"] = months == 12
        pg.screenshot(path=str(EVID / "year.png"))

        # ---- working-hours shading in week view ----
        pg.eval_on_selector('.cal-view-btn[data-view="week"]', "el => el.click()")
        pg.wait_for_selector(".cal-tg-slot", timeout=8000)
        r["working_hours_shaded"] = pg.query_selector(".cal-tg-slot.offhours") is not None

        # ---- subscribe to an ICS feed via the UI (2 prompts) ----
        pg.eval_on_selector("#cal-feed-add", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)
        pg.fill("#_di", "https://example.com/holidays.ics")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)  # second prompt (name)
        pg.fill("#_di", "Holidays")
        pg.eval_on_selector("#_dy", "el => el.click()")
        added = False
        for _ in range(20):
            pg.wait_for_timeout(400)
            added = pg.evaluate(
                "() => fetch('/api/calendar/subscriptions').then(r=>r.json()).then(a=>a.length>=1)"
            )
            if added:
                break
        r["subscription_add"] = bool(added)

        # ---- the feed shows in the sidebar list ----
        pg.wait_for_selector(".cal-feed-row", timeout=8000)
        r["subscription_lists"] = pg.query_selector(".cal-feed-row .cal-feed-name") is not None
        pg.screenshot(path=str(EVID / "feeds.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_calendar_views_8a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""4a - verify the editor scheduling advisor end to end: a live overlap warning when the
proposed time double-books, and a free-slot finder that fills the time on click.

runs against an owned throwaway server like the other gates: PORT and ALLES_TEST_RUN_ID come
from the gate runner.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

# the browser's zone is pinned and "today" is counted there, whatever zone the runner has
ZONE = "America/Toronto"


def main():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    today = datetime.now(ZoneInfo(ZONE)).date().isoformat()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block", timezone_id=ZONE).new_page()
        assert pg.request.post(base + "/api/setup/dismiss").ok
        pg.goto(base + "/?view=calendar", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        ids = pg.evaluate(
            """async (today) => {
                const mk = (t, sh, eh) => fetch('/api/calendar', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({title:t, start_dt:`${today}T${sh}`, end_dt:`${today}T${eh}`, all_day:false})}).then(r=>r.json()).then(j=>j.id);
                const a = await mk('ADV_A', '10:00', '11:00');
                const bb = await mk('ADV_B', '10:30', '11:30');  // overlaps A
                return [a, bb];
            }""",
            today,
        )
        bid = ids[1]
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        # a short month cell keeps one event and folds the rest into "+1 more": open the day,
        # where a timed event opens on a real press (it can also be dragged)
        pg.click(f".cal-more[data-day='{today}'], .cal-day-open[data-day='{today}']")
        pg.wait_for_timeout(500)
        pg.click(f".cal-tev[data-id='{bid}']")
        pg.wait_for_timeout(800)
        warn = pg.evaluate("() => document.getElementById('cal-conflict')?.textContent || ''")
        assert "overlaps" in warn and "ADV_A" in warn, warn

        pg.click("#cal-freeslot")
        pg.wait_for_timeout(700)
        chips = pg.evaluate(
            "() => [...document.querySelectorAll('.cal-slot-chip')].map(c=>c.textContent.trim())"
        )
        assert chips, "expected at least one free-slot chip"
        pg.evaluate(
            "() => [...document.querySelectorAll('.cal-slot-chip')].find(c=>c.textContent.includes('11:30'))?.click()"
        )
        pg.wait_for_timeout(600)
        assert "11:30" in (pg.evaluate("() => document.getElementById('cal-start')?.value") or "")
        assert (
            pg.evaluate("() => document.getElementById('cal-conflict')?.textContent") or ""
        ) == ""

        pg.evaluate(
            "async (ids) => { for (const id of ids) await fetch('/api/calendar/'+id, {method:'DELETE'}); }",
            ids,
        )
        b.close()
    print("PASS: conflict warning + free-slot finder both work")


if __name__ == "__main__":
    main()

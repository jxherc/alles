"""4a - verify the editor scheduling advisor end to end: a live overlap warning when the
proposed time double-books, and a free-slot finder that fills the time on click.

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_adv AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_calendar_advisor.py
"""
from datetime import date

from playwright.sync_api import sync_playwright

BASE = "http://calendar.localhost:8077"


def main():
    today = date.today().isoformat()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        ids = pg.evaluate(
            """async (today) => {
                const mk = (t, sh, eh) => fetch('/api/calendar', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({title:t, start_dt:`${today}T${sh}`, end_dt:`${today}T${eh}`, all_day:false})}).then(r=>r.json()).then(j=>j.id);
                const a = await mk('ADV_A', '10:00', '11:00');
                const bb = await mk('ADV_B', '10:30', '11:30');  // overlaps A
                return [a, bb];
            }""", today,
        )
        bid = ids[1]
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        pg.evaluate("(bid) => document.querySelector(`[data-id='${bid}']`)?.click()", bid)
        pg.wait_for_timeout(800)
        warn = pg.evaluate("() => document.getElementById('cal-conflict')?.textContent || ''")
        assert "overlaps" in warn and "ADV_A" in warn, warn

        pg.click("#cal-freeslot")
        pg.wait_for_timeout(700)
        chips = pg.evaluate("() => [...document.querySelectorAll('.cal-slot-chip')].map(c=>c.textContent.trim())")
        assert chips, "expected at least one free-slot chip"
        pg.evaluate("() => [...document.querySelectorAll('.cal-slot-chip')].find(c=>c.textContent.includes('11:30'))?.click()")
        pg.wait_for_timeout(600)
        assert "11:30" in (pg.evaluate("() => document.getElementById('cal-start')?.value") or "")
        assert (pg.evaluate("() => document.getElementById('cal-conflict')?.textContent") or "") == ""

        pg.evaluate("async (ids) => { for (const id of ids) await fetch('/api/calendar/'+id, {method:'DELETE'}); }", ids)
        b.close()
    print("PASS: conflict warning + free-slot finder both work")


if __name__ == "__main__":
    main()

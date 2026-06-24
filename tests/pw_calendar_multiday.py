"""verify a multi-day all-day event renders on every day it spans in the calendar month view."""
from datetime import date
from playwright.sync_api import sync_playwright

BASE = "http://calendar.localhost:8077"


def main():
    today = date.today()
    # 3-day all-day event on the 10th-12th of the current month (visible in the default month grid)
    s = today.replace(day=10).isoformat()
    e = today.replace(day=12).isoformat()
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        # create the event against the real backend, then reload the calendar
        pg.evaluate(
            """async ([s, e]) => {
                await fetch('/api/calendar', { method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({ title:'MULTIDAY_TRIP', start_dt:s, end_dt:e, all_day:true }) });
            }""",
            [s, e],
        )
        pg.evaluate("() => window._navigateTo && window._navigateTo('calendar')")
        pg.wait_for_timeout(1200)
        cells = pg.evaluate("""() => {
            const out = [];
            document.querySelectorAll('.cal-cell[data-date]').forEach(c => {
                if ([...c.querySelectorAll('.cal-chip')].some(ch => (ch.textContent||'').includes('MULTIDAY_TRIP'))) out.push(c.dataset.date);
            });
            return out;
        }""")
        print("days showing the event:", cells)
        assert len(cells) >= 3, f"multi-day event only on {len(cells)} day(s): {cells}"
        assert cells == sorted(cells) and cells[0].endswith('-10') and cells[-1].endswith('-12'), cells
        print("PASS: spans all 3 days")
        # cleanup
        pg.evaluate("""async () => {
            const evs = await fetch('/api/calendar').then(r=>r.json());
            const list = Array.isArray(evs) ? evs : (evs.events||[]);
            for (const ev of list) if (ev.title==='MULTIDAY_TRIP') await fetch('/api/calendar/'+ev.id, {method:'DELETE'});
        }""")
        b.close()
    print("ALL GOOD")


if __name__ == "__main__":
    main()

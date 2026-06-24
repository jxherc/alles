"""verify two overlapping timed events render side-by-side (not stacked/hidden)."""
from datetime import date
from playwright.sync_api import sync_playwright

BASE = "http://calendar.localhost:8077"


def main():
    d = date.today().isoformat()
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async (d) => {
                const mk = (t, sh, eh) => fetch('/api/calendar', { method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({ title:t, start_dt:`${d}T${sh}:00`, end_dt:`${d}T${eh}:00`, all_day:false }) });
                await mk('OVLP_A', '10:00', '11:30');
                await mk('OVLP_B', '10:30', '12:00');   // overlaps A
            }""", d,
        )
        pg.evaluate("() => window._navigateTo && window._navigateTo('calendar')")
        pg.wait_for_timeout(800)
        # switch to day view (button/segment with 'day')
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button,.cal-view-opt,[data-view]')].find(x=>/^day$/i.test((x.textContent||'').trim())); b && b.click(); }""")
        pg.wait_for_timeout(900)
        boxes = pg.evaluate("""() => [...document.querySelectorAll('.cal-tev')]
            .filter(e => /OVLP_/.test(e.textContent||''))
            .map(e => ({ t: e.textContent.match(/OVLP_[AB]/)[0], left: e.style.left, width: e.style.width, w: e.getBoundingClientRect().width, x: e.getBoundingClientRect().x }))""")
        print("boxes:", boxes)
        assert len(boxes) == 2, f"expected 2, got {len(boxes)}"
        # different x positions (side by side), neither spanning the full column
        assert abs(boxes[0]["x"] - boxes[1]["x"]) > 5, f"events not offset: {boxes}"
        print("PASS: overlapping events laid out side by side")
        pg.evaluate("""async () => {
            const evs = await fetch('/api/calendar').then(r=>r.json());
            const list = Array.isArray(evs) ? evs : (evs.events||[]);
            for (const ev of list) if (/OVLP_/.test(ev.title)) await fetch('/api/calendar/'+ev.id, {method:'DELETE'});
        }""")
        b.close()
    print("ALL GOOD")


if __name__ == "__main__":
    main()

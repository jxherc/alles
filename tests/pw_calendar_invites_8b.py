"""8b UI — event invites + RSVP status, video-call link, booking-page manager + public booking.
calendar.localhost:8865.  ALLES_DATA=/tmp/alles8b PORT=8865 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CAL = "http://calendar.localhost:8865"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "8b"
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

        # seed an event and open its editor
        eid = pg.evaluate(
            "() => fetch('/api/calendar',{method:'POST',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({title:'Launch sync',start_dt:'2026-07-10T10:00:00'})}).then(r=>r.json()).then(e=>e.id)"
        )
        # reload so the in-memory event list includes the freshly seeded event
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#calendar-view", timeout=12000)
        pg.wait_for_timeout(500)
        # open the editor for THIS event (match by data-id so prior-run events don't interfere)
        pg.eval_on_selector('.cal-view-btn[data-view="agenda"]', "el => el.click()")
        pg.wait_for_selector(f'.cal-agenda-ev[data-id="{eid}"]', timeout=8000)
        pg.eval_on_selector(f'.cal-agenda-ev[data-id="{eid}"]', "el => el.click()")
        pg.wait_for_selector("#cal-meeting", timeout=8000)

        # ---- video-call link generator fills the field ----
        pg.eval_on_selector("#cal-meet-gen", "el => el.click()")
        for _ in range(20):
            pg.wait_for_timeout(250)
            if (pg.input_value("#cal-meeting") or "").startswith("http"):
                break
        r["video_button_fills_link"] = (pg.input_value("#cal-meeting") or "").startswith("http")

        # ---- invite adds an attendee ----
        pg.fill("#cal-inv-name", "Sam Carter")
        pg.fill("#cal-inv-email", "sam@example.com")
        pg.eval_on_selector("#cal-inv-btn", "el => el.click()")
        pg.wait_for_selector(".cal-inv-row", timeout=8000)
        r["invite_adds_attendee"] = "Sam Carter" in (pg.text_content("#cal-invites") or "")
        r["attendee_status_shows"] = pg.query_selector(".cal-inv-status") is not None
        pg.screenshot(path=str(EVID / "event-invites.png"))

        # ---- RSVP via the public page updates status ----
        tok = pg.evaluate(
            "eid => fetch('/api/calendar/'+eid+'/attendees').then(r=>r.json()).then(a=>a[0].token)",
            eid,
        )
        pg.evaluate(
            "tok => fetch('/rsvp/'+tok,{method:'POST',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({status:'accepted'})})",
            tok,
        )
        status = pg.evaluate(
            "eid => fetch('/api/calendar/'+eid+'/attendees').then(r=>r.json()).then(a=>a[0].status)",
            eid,
        )
        r["rsvp_updates_status"] = status == "accepted"

        # back to the calendar, create a booking page
        pg.eval_on_selector("#cal-back", "el => el.click()")
        pg.wait_for_selector("#cal-book-add", timeout=8000)
        pg.eval_on_selector("#cal-book-add", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)
        pg.fill("#_di", "Office hours")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)
        pg.fill("#_di", "30")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector(".cal-bookings .cal-feed-row", timeout=8000)
        r["booking_page_create"] = pg.query_selector(".cal-bookings .cal-feed-name") is not None

        # ---- the public booking page lists slots + a booking creates an event ----
        tok2 = pg.evaluate(
            "() => fetch('/api/calendar/booking-pages').then(r=>r.json()).then(a=>a[0].token)"
        )
        pg.goto(f"{CAL}/book/{tok2}", wait_until="domcontentloaded")
        pg.wait_for_selector(".slot", timeout=10000)
        r["booking_public_lists_slots"] = pg.query_selector(".slot") is not None
        pg.screenshot(path=str(EVID / "booking-page.png"))
        before = pg.evaluate("() => fetch('/api/calendar').then(r=>r.json()).then(a=>a.length)")
        pg.eval_on_selector(".slot", "el => el.click()")
        pg.fill("#name", "Booker")
        pg.fill("#email", "book@example.com")
        pg.eval_on_selector("button.go", "el => el.click()")
        made = False
        for _ in range(20):
            pg.wait_for_timeout(300)
            now = pg.evaluate("() => fetch('/api/calendar').then(r=>r.json()).then(a=>a.length)")
            if now > before:
                made = True
                break
        r["booking_creates_event"] = made

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_calendar_invites_8b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

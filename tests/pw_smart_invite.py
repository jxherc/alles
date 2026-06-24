"""4a - verify smart-invite end to end: inviting a known contact surfaces their linked contacts
as one-click chips; clicking a chip invites that person and drops them from the suggestions.

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_si AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_smart_invite.py
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
        eid = pg.evaluate(
            """async (today) => {
                const mkc = (n,e) => fetch('/api/contacts', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({name:n, email:e})}).then(r=>r.json()).then(j=>j.id);
                const ann = await mkc('Ann Stark', 'ann@x.com');
                const bob = await mkc('Bob Stark', 'bob@x.com');
                await fetch('/api/contacts/'+ann+'/links', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({to_id:bob, kind:'spouse'})});
                const ev = await fetch('/api/calendar', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({title:'SMARTINV', start_dt: today, end_dt: today, all_day: true})}).then(r=>r.json());
                await fetch('/api/calendar/'+ev.id+'/invite', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({name:'Ann Stark', email:'ann@x.com'})});
                return ev.id;
            }""", today,
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        pg.evaluate("(eid) => document.querySelector(`[data-id='${eid}']`)?.click()", eid)
        pg.wait_for_timeout(900)
        sug = pg.evaluate("() => document.getElementById('cal-inv-suggest')?.textContent || ''")
        assert "Bob Stark" in sug and "spouse" in sug, sug

        pg.evaluate("() => document.querySelector('.cal-inv-chip')?.click()")
        pg.wait_for_timeout(900)
        who = pg.evaluate("() => [...document.querySelectorAll('.cal-inv-who')].map(x=>x.textContent)")
        assert any("Bob" in w for w in who), who
        assert "Bob Stark" not in (pg.evaluate("() => document.getElementById('cal-inv-suggest')?.textContent") or "")
        b.close()
    print("PASS: smart-invite suggests, one-click invites, and drops the invited contact")


if __name__ == "__main__":
    main()

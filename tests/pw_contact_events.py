"""4a CRM-lite - verify the contact detail shows a shared-events timeline (upcoming first, past dimmed).

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_ce AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_contact_events.py
"""
from playwright.sync_api import sync_playwright

BASE = "http://contacts.localhost:8077"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        cid = pg.evaluate(
            """async () => {
                const cid = await fetch('/api/contacts', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({name:'Ada Lovelace', email:'ada@x.com'})}).then(r=>r.json()).then(j=>j.id);
                const mk = async (t, when) => {
                    const ev = await fetch('/api/calendar', {method:'POST', headers:{'content-type':'application/json'},
                      body: JSON.stringify({title:t, start_dt:when, end_dt:when, all_day:true})}).then(r=>r.json());
                    await fetch('/api/calendar/'+ev.id+'/invite', {method:'POST', headers:{'content-type':'application/json'},
                      body: JSON.stringify({name:'Ada Lovelace', email:'ada@x.com'})});
                };
                await mk('Past Workshop', '2020-03-01');
                await mk('Future Summit', '2030-09-09');
                return cid;
            }"""
        )
        pg.evaluate("(cid) => window._editContact(cid)", cid)
        pg.wait_for_timeout(700)
        rows = pg.evaluate(
            """() => [...document.querySelectorAll('.cd-ev-row')].map(r => ({
                title: r.querySelector('.cd-ev-title').textContent,
                past: r.classList.contains('past') }))"""
        )
        assert [r["title"] for r in rows] == ["Future Summit", "Past Workshop"], rows
        assert rows[0]["past"] is False and rows[1]["past"] is True, rows
        pg.evaluate("(cid) => fetch('/api/contacts/'+cid, {method:'DELETE'})", cid)
        b.close()
    print("PASS: contact shared-events timeline renders, upcoming-first with past dimmed")


if __name__ == "__main__":
    main()

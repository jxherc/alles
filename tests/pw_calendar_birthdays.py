"""4a - verify contact birthdays render as an overlay on the calendar month view.

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_bd AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_calendar_birthdays.py
"""
from datetime import date

from playwright.sync_api import sync_playwright

BASE = "http://calendar.localhost:8077"


def main():
    today = date.today()
    bd = f"1990-{today.month:02d}-15"
    cell = f"{today.year}-{today.month:02d}-15"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        cid = pg.evaluate(
            """(bd) => fetch('/api/contacts', {method:'POST', headers:{'content-type':'application/json'},
                 body: JSON.stringify({name:'Grace Hopper', birthday: bd})}).then(r=>r.json()).then(j=>j.id)""",
            bd,
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        txt = pg.evaluate(
            """(cell) => {
                const c = document.querySelector(`.cal-cell[data-date='${cell}']`);
                return c ? [...c.querySelectorAll('.cal-bday')].map(b => b.textContent.trim()).join('|') : '(no cell)';
            }""", cell,
        )
        assert "Grace Hopper" in txt, txt
        pg.evaluate("(cid) => fetch('/api/contacts/'+cid, {method:'DELETE'})", cid)
        b.close()
    print("PASS: contact birthday shows on the calendar")


if __name__ == "__main__":
    main()

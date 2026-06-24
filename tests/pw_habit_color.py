"""4 - verify the habit editor color picker sets + persists a habit's accent color.

needs a fresh instance: ALLES_DATA=.tmp_hc AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_habit_color.py
"""
from playwright.sync_api import sync_playwright

BASE = "http://habits.localhost:8077"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        hid = pg.evaluate(
            """() => fetch('/api/habits', {method:'POST', headers:{'content-type':'application/json'},
                body: JSON.stringify({name:'Run'})}).then(r=>r.json()).then(j=>j.id)"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.click(f'.habit-card[data-id="{hid}"] [data-act="edit"]')
        pg.wait_for_timeout(400)
        # pick the green swatch
        pg.click('.habit-colors .habit-sw[data-c="#34d399"]')
        sel = pg.evaluate("() => document.querySelector('.habit-colors')?.dataset.value")
        print("selected color:", sel)
        assert sel == "#34d399", sel
        pg.click('[data-act="save"]')
        pg.wait_for_timeout(800)
        accent = pg.evaluate(
            f"""() => document.querySelector('.habit-card[data-id="{hid}"]')?.style.getPropertyValue('--habit-accent')"""
        )
        print("card accent after save:", accent)
        assert "#34d399" in (accent or ""), accent
        api = pg.evaluate("() => fetch('/api/habits/overview').then(r=>r.json()).then(j=>j.habits[0].color)")
        assert api == "#34d399", api
        b.close()
    print("PASS: habit color picker sets + persists the accent")


if __name__ == "__main__":
    main()

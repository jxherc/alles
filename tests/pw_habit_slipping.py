"""4b - verify a habit you've let slide (old + unlogged) gets a 'slipping' badge; an active one doesn't.

seeds directly into the running server's DB (created_at can't be backdated via the API), so set
the SAME data dir for both the server and this script:
  ALLES_DATA=.tmp_hs AUTH_ENABLED=false PORT=8077 python app.py
  ALLES_DATA=.tmp_hs PYTHONPATH=. PYTHONIOENCODING=utf-8 python tests/pw_habit_slipping.py
"""
import os
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

from core.database import Habit, HabitLog, SessionLocal

BASE = "http://habits.localhost:8077"


def seed():
    s = SessionLocal()
    old = datetime.utcnow() - timedelta(days=30)
    slip = Habit(name="Meditate", created_at=old)   # old, never logged -> slipping
    active = Habit(name="Read", created_at=old)      # old, logged daily -> not slipping
    s.add_all([slip, active])
    s.commit()
    today = datetime.utcnow().date()
    for i in range(12):
        s.add(HabitLog(habit_id=active.id, date=(today - timedelta(days=i)).isoformat()))
    s.commit()
    s.close()


def main():
    assert os.environ.get("ALLES_DATA"), "set ALLES_DATA to the running server's data dir"
    seed()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        cards = pg.evaluate(
            """() => [...document.querySelectorAll('.habit-card[data-id]')].map(c => ({
                name: c.querySelector('.habit-name')?.textContent,
                slip: !!c.querySelector('.habit-slip') }))"""
        )
        assert next(c for c in cards if c["name"] == "Meditate")["slip"], cards
        assert not next(c for c in cards if c["name"] == "Read")["slip"], cards
        b.close()
    print("PASS: slipping habit flagged, active habit clean")


if __name__ == "__main__":
    main()

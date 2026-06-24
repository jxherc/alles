"""4b - verify the read-later capacity planner bar shows queue size + total time + days to clear.

seeds directly into the running server's DB, so set the SAME data dir for both:
  ALLES_DATA=.tmp_rc AUTH_ENABLED=false PORT=8077 python app.py
  ALLES_DATA=.tmp_rc PYTHONPATH=. PYTHONIOENCODING=utf-8 python tests/pw_read_capacity.py
"""
import os

from playwright.sync_api import sync_playwright

from core.database import ReadItem, SessionLocal

BASE = "http://read.localhost:8077"


def seed():
    s = SessionLocal()
    for i, m in enumerate([15, 30, 45, 60]):  # 150 min total unread
        s.add(ReadItem(url=f"u{i}", title=f"Article {i}", text="x", excerpt="e", read_minutes=m))
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
        bar = pg.evaluate("() => document.querySelector('.read-stats')?.textContent || ''")
        assert "4 unread" in bar and "2h 30m" in bar and "8 days" in bar, bar
        b.close()
    print("PASS: read capacity planner bar correct")


if __name__ == "__main__":
    main()

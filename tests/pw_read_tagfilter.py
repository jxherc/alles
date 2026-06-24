"""4 - verify clicking a tag filters the read list and 'clear' restores it.

seeds into the running server DB - set the SAME data dir:
  ALLES_DATA=.tmp_rt AUTH_ENABLED=false PORT=8077 python app.py
  ALLES_DATA=.tmp_rt PYTHONPATH=. PYTHONIOENCODING=utf-8 python tests/pw_read_tagfilter.py
"""
import os

os.environ["ALLES_DATA"] = ".tmp_relverify_data"
os.environ["AUTH_ENABLED"] = "false"

from playwright.sync_api import sync_playwright  # noqa: E402

from core.database import ReadItem, SessionLocal  # noqa: E402

BASE = "http://read.localhost:8077"


def seed():
    s = SessionLocal()
    s.add(ReadItem(url="a", title="Python article", text="x", excerpt="e", tags="python, ml", read_minutes=5))
    s.add(ReadItem(url="b", title="Cooking article", text="x", excerpt="e", tags="cooking", read_minutes=5))
    s.add(ReadItem(url="c", title="ML paper", text="x", excerpt="e", tags="python", read_minutes=5))
    s.commit()
    s.close()


def titles(pg):
    return pg.evaluate("() => [...document.querySelectorAll('.read-card-title')].map(t => t.textContent.trim())")


def main():
    seed()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(900)
        assert len(titles(pg)) == 3, titles(pg)
        # click a 'python' tag on a card
        pg.evaluate("""() => [...document.querySelectorAll('.read-tag')].find(t => t.textContent.includes('python')).click()""")
        pg.wait_for_timeout(700)
        ts = titles(pg)
        print("after #python:", ts)
        assert set(ts) == {"Python article", "ML paper"}, ts
        banner = pg.evaluate("() => document.querySelector('.read-tagfilter')?.textContent || ''")
        assert "#python" in banner, banner
        # clear
        pg.click("#read-tag-clear")
        pg.wait_for_timeout(700)
        assert len(titles(pg)) == 3, titles(pg)
        b.close()
    print("PASS: tag filter narrows the list and clear restores it")


if __name__ == "__main__":
    main()

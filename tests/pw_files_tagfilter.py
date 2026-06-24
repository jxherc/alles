"""4c - verify clicking a file tag opens a 'tagged #x' view listing every file with that tag.

seeds into the running server DB+disk - set the SAME data dir:
  ALLES_DATA=.tmp_ft AUTH_ENABLED=false PORT=8077 python app.py
  ALLES_DATA=.tmp_ft PYTHONPATH=. PYTHONIOENCODING=utf-8 python tests/pw_files_tagfilter.py
"""
import os

os.environ["ALLES_DATA"] = ".tmp_relverify_data"
os.environ["AUTH_ENABLED"] = "false"

from playwright.sync_api import sync_playwright  # noqa: E402

from core.database import FileTag, SessionLocal  # noqa: E402
from core.settings import data_dir  # noqa: E402

BASE = "http://files.localhost:8077"


def seed():
    fdir = data_dir() / "files"
    fdir.mkdir(parents=True, exist_ok=True)
    for name in ("report.txt", "notes.txt", "budget.txt"):
        (fdir / name).write_text("x")
    s = SessionLocal()
    s.add(FileTag(path="report.txt", tags="work,urgent"))
    s.add(FileTag(path="notes.txt", tags="work"))
    s.add(FileTag(path="budget.txt", tags="home"))
    s.commit()
    s.close()


def names(pg):
    return pg.evaluate("() => [...document.querySelectorAll('.file-row .file-name')].map(n => n.textContent.replace(/work|urgent|home/g,'').trim())")


def main():
    seed()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        # click the #work tag on report.txt
        pg.evaluate("""() => [...document.querySelectorAll('.file-tag[data-tag="work"]')][0].click()""")
        pg.wait_for_timeout(800)
        ns = names(pg)
        print("tagged-work view:", ns)
        assert "report.txt" in ns and "notes.txt" in ns and "budget.txt" not in ns, ns
        crumb = pg.evaluate("() => document.querySelector('.files-crumb, .files-breadcrumb, .file-crumb')?.textContent || document.body.innerText.includes('tagged #work')")
        print("crumb shows tag:", crumb)
        b.close()
    print("PASS: file tag click lists every file with that tag")


if __name__ == "__main__":
    main()

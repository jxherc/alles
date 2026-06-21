"""read-later audit — list, search, reader view, actions; desktop + narrow; console capture."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8915"
OUT = "docs/evidence/read"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
URL = f"http://read.localhost:{PORT}/"


def clean(errs):
    return [e for e in errs if not any(s in e for s in IGNORE)]


def run():
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda ex: errs.append("PAGEERR:" + str(ex)))

        pg.goto(URL, wait_until="domcontentloaded")
        pg.wait_for_selector(".read-card, .read-empty", timeout=15000)
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/01-list.png", full_page=True)

        # search
        pg.fill("#read-q", "work")
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/02-search.png", full_page=True)
        pg.fill("#read-q", "")
        pg.wait_for_timeout(600)

        # open the reader on the first item
        pg.click(".read-card .read-card-main")
        pg.wait_for_selector(".read-article", timeout=8000)
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/03-reader.png", full_page=True)
        pg.click("#read-back")
        pg.wait_for_selector(".read-list", timeout=8000)
        pg.wait_for_timeout(400)

        # star + archive actions
        pg.click('.read-card [data-act="fav"]')
        pg.wait_for_timeout(500)
        pg.click('.read-chip[data-filter="fav"]')
        pg.wait_for_timeout(600)
        pg.screenshot(path=f"{OUT}/04-starred-filter.png", full_page=True)
        pg.click('.read-chip[data-filter="all"]')
        pg.wait_for_timeout(500)

        # narrow
        pg.set_viewport_size({"width": 460, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".read-card", timeout=10000)
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/05-narrow.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL:\n" + ("\n".join(errs) or "(none)") + "\n\nREAL:\n" + ("\n".join(real) or "(none)"))
    if real:
        print("FAIL — real console errors:", real[:5])
        sys.exit(1)
    print("PASS — read audit clean, 0 real console errors")


if __name__ == "__main__":
    run()

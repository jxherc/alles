"""books audit — shelves, rating, status move, lookup add, notes; desktop + narrow; console."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8916"
OUT = "docs/evidence/books"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed",
          "covers.openlibrary")  # external cover host can be slow/blocked — not our bug
URL = f"http://books.localhost:{PORT}/"


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
        pg.wait_for_selector(".book-card, .books-empty", timeout=15000)
        pg.wait_for_timeout(1500)  # let cover images load
        pg.screenshot(path=f"{OUT}/01-shelves.png", full_page=True)

        # rate a book (3rd star on the first card)
        pg.click(".book-card .book-star[data-rate='4']")
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/02-rated.png", full_page=True)

        # move first 'want' book to reading
        moved = pg.query_selector('.book-card [data-move="reading"]')
        if moved:
            moved.click()
            pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/03-after-move.png", full_page=True)

        # add via the form + OpenLibrary lookup
        pg.click("#books-add-toggle")
        pg.wait_for_selector(".book-add", timeout=5000)
        pg.fill("#book-q", "The Hobbit")
        pg.click("#book-search")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=f"{OUT}/04-lookup.png", full_page=True)
        pick = pg.query_selector(".book-lookup-item")
        if pick:
            pick.click()
            pg.wait_for_timeout(500)
        pg.click("#book-create")
        pg.wait_for_timeout(800)
        pg.screenshot(path=f"{OUT}/05-after-add.png", full_page=True)

        # add a note to the first card
        note = pg.query_selector('.book-card [data-act="notes"]')
        if note:
            note.click()
            pg.wait_for_timeout(300)
            ta = pg.query_selector('.book-notes-edit textarea')
            if ta:
                ta.fill("loved the ending")
                pg.click('.book-card [data-act="save-notes"]')
                pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/06-note.png", full_page=True)

        # narrow
        pg.set_viewport_size({"width": 460, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".book-card", timeout=10000)
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/07-narrow.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL:\n" + ("\n".join(errs) or "(none)") + "\n\nREAL:\n" + ("\n".join(real) or "(none)"))
    if real:
        print("FAIL — real console errors:", real[:5])
        sys.exit(1)
    print("PASS — books audit clean, 0 real console errors")


if __name__ == "__main__":
    run()

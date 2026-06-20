"""ui-3k verify — canvas/board/tasks moved to the docs home; bookmark works from a
doc card; the in-doc toolbar no longer carries canvas/board/tasks/bookmark."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1500)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # home: new-canvas / new-board / tasks present
        home = pg.evaluate("""() => ({
          canvas: !!document.querySelector('#wiki-home-canvas'),
          board: !!document.querySelector('#wiki-home-board'),
          tasks: !!document.querySelector('#wiki-home-tasks'),
          cards: document.querySelectorAll('.docs-card').length,
          stars: document.querySelectorAll('.docs-card-star').length,
        })""")
        ok("home has + new canvas", home["canvas"])
        ok("home has + new board", home["board"])
        ok("home has tasks", home["tasks"])
        ok("doc cards render", home["cards"] >= 1)
        ok("each card has a bookmark star", home["stars"] == home["cards"])

        # bookmark via a card star → bookmarks strip appears
        pg.eval_on_selector(".docs-card-star", "el => el.click()")
        pg.wait_for_timeout(600)
        bm = pg.evaluate("() => ({strip: !!document.querySelector('#docs-bookmarks'), starOn: !!document.querySelector('.docs-card-star.on')})")
        ok("bookmarking from a card shows the bookmarks strip", bm["strip"])
        ok("the card star turns on", bm["starOn"])

        # open a doc → in-doc toolbar no longer has the 4 moved buttons
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(900)
        gone = pg.evaluate("""() => ({
          canvas: !!document.querySelector('#wiki-canvas-btn'),
          board: !!document.querySelector('#wiki-board-btn'),
          tasks: !!document.querySelector('#wiki-taskroll-btn'),
          bm: !!document.querySelector('#wiki-bookmark-btn'),
        })""")
        ok("in-doc canvas button gone", not gone["canvas"])
        ok("in-doc board button gone", not gone["board"])
        ok("in-doc tasks button gone", not gone["tasks"])
        ok("in-doc bookmark button gone", not gone["bm"])

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

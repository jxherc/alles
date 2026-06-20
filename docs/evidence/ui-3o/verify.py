"""ui-3o verify — split view: opening split prompts a doc picker (open/all scope),
picking loads it ~50/50, and the divider is draggable to re-proportion."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1300, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        # need >=2 docs for a meaningful picker; create a second
        pg.evaluate("""async () => {
          await fetch('/api/vault-md/file', {method:'POST', headers:{'content-type':'application/json'},
            body: JSON.stringify({path:'second.md', content:'second doc body'})});
        }""")
        pg.wait_for_timeout(300)
        pg.evaluate("() => { if (window.location) location.reload(); }")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1500)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1100)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        pg.click("#wiki-split-btn")
        pg.wait_for_timeout(400)
        picker = pg.query_selector("#split-picker")
        ok("opening split prompts a doc picker", picker is not None)
        if picker:
            ok("picker has open/all scope tabs", picker.query_selector(".sp-tab[data-s='open']") is not None and picker.query_selector(".sp-tab[data-s='all']") is not None)
            items = picker.query_selector_all(".sp-item")
            ok("picker lists docs to choose", len(items) >= 1)
            items[0].click()
            pg.wait_for_timeout(600)
        d = pg.evaluate("""() => {
          const v = document.querySelector('#wiki-view');
          const pane = document.querySelector('#wiki-split-pane');
          const div = document.querySelector('#wiki-split-divider');
          const cs = pane ? getComputedStyle(pane) : null;
          return {
            splitOn: v.classList.contains('split-on'),
            paneShown: cs && cs.display !== 'none',
            dividerShown: div && getComputedStyle(div).display !== 'none',
            paneBody: (document.querySelector('.wiki-split-body')?.textContent || '').slice(0, 40),
            paneW: cs ? parseInt(cs.width) : 0,
          };
        }""")
        ok("split mode is on", d["splitOn"])
        ok("the picked doc pane is shown", d["paneShown"])
        ok("a draggable divider is shown", d["dividerShown"])
        ok("pane is roughly half width", 400 < d["paneW"] < 850)
        ok("the picked doc content loaded", len(d["paneBody"]) > 0)

        # drag the divider left → pane gets wider
        box = pg.query_selector("#wiki-split-divider").bounding_box()
        pg.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(box["x"] - 200, box["y"] + box["height"] / 2, steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(300)
        w2 = pg.evaluate("() => parseInt(getComputedStyle(document.querySelector('#wiki-split-pane')).width)")
        ok("dragging the divider re-proportions the panes", w2 > d["paneW"] + 80)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3o/split.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

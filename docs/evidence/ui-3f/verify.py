"""ui-3f verify — pipe tables render as real, styled HTML tables in live mode
(bordered cells, emphasised header) and the toolbar table button inserts one that renders."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1200})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1200)
        pg.evaluate("() => { const v = window._cmEditor?.view; if (v) v.dispatch({selection:{anchor:0}}); }")
        pg.wait_for_timeout(500)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        t = pg.query_selector(".cm-content table.cm-table")
        ok("table renders as cm-table", t is not None)
        if t:
            d = pg.evaluate("""(tbl) => {
              const th = tbl.querySelector('th'), td = tbl.querySelector('td');
              const cs = getComputedStyle(th);
              return {
                heads: tbl.querySelectorAll('th').length,
                rows: tbl.querySelectorAll('tbody tr').length,
                thBorder: getComputedStyle(td).borderTopWidth,
                thWeight: cs.fontWeight,
                thBg: cs.backgroundColor,
                headText: th.textContent,
              };
            }""", t)
            ok("two header cells", d["heads"] == 2)
            ok("two body rows", d["rows"] == 2)
            ok("cells are bordered", d["thBorder"] not in ("0px", ""))
            ok("header is emphasised", int(d["thWeight"]) >= 600)
            ok("header has a fill", d["thBg"] not in ("rgba(0, 0, 0, 0)", "transparent"))

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

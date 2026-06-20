"""ui-3h verify — text selection stays inside the centered content column (no bleed
into the empty side margins). Select-all in live mode, measure the selection layer."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"


def run():
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1200)
        pg.evaluate(
            "() => { const v = window._cmEditor.view; v.focus();"
            " v.dispatch({selection:{anchor:0, head:v.state.doc.length}}); }"
        )
        pg.wait_for_timeout(500)
        d = pg.evaluate("""() => {
          const ed = document.querySelector('.cm-editor').getBoundingClientRect();
          const sels = [...document.querySelectorAll('.cm-selectionBackground')];
          let maxR = 0, minL = 1e9;
          sels.forEach(s => { const r = s.getBoundingClientRect(); maxR = Math.max(maxR, r.right); minL = Math.min(minL, r.left); });
          return {edLeft: ed.left, edRight: ed.right, edWidth: ed.width, vw: window.innerWidth, selMaxR: maxR, selMinL: minL, n: sels.length};
        }""")

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("editor column is capped (<=860px)", d["edWidth"] <= 860)
        ok("editor is centered (side gutters exist)", d["edLeft"] > 40 and (d["vw"] - d["edRight"]) > 40)
        ok("selection exists", d["n"] > 0)
        ok("selection right edge stays within the column", d["selMaxR"] <= d["edRight"] + 2)
        ok("selection left edge stays within the column", d["selMinL"] >= d["edLeft"] - 2)
        print("measures:", d)
        b.close()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("ALL GREEN")


if __name__ == "__main__":
    run()

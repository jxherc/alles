"""ui-3q verify — open-tabs strip: open tab gets a squircle outline, inactive tabs are
plain (no box), and deleting a doc drops it from the tab strip."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        # create a 2nd doc so we have two tabs, then open both
        pg.evaluate("""async () => {
          await fetch('/api/vault-md/file', {method:'POST', headers:{'content-type':'application/json'},
            body: JSON.stringify({path:'tabtwo.md', content:'tab two'})});
        }""")
        pg.wait_for_timeout(300)
        pg.evaluate("() => location.reload()")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1500)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(800)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"tabtwo.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(900)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const tabs = [...document.querySelectorAll('.wiki-tab')];
          const act = document.querySelector('.wiki-tab.active');
          const inact = tabs.find(t => !t.classList.contains('active'));
          const cs = el => el ? getComputedStyle(el) : null;
          const a = cs(act), i = cs(inact);
          const wrap = cs(document.querySelector('.wiki-tabs'));
          return {
            count: tabs.length,
            activeBorder: a ? a.borderTopColor : '',
            activeRadius: a ? a.borderTopLeftRadius : '',
            inactBorder: i ? i.borderTopColor : '',
            padLeft: wrap ? wrap.paddingLeft : '',
          };
        }""")
        ok("two tabs open", d["count"] == 2)
        ok("open tab has an outline (accent)", d["activeBorder"] not in TRANSPARENT)
        ok("open tab is a squircle (rounded)", d["activeRadius"] not in ("0px", ""))
        ok("inactive tab has no outline box", d["inactBorder"] in TRANSPARENT)
        ok("no dead left gutter (small padding)", d["padLeft"] not in ("", "0px") and float(d["padLeft"].replace("px", "")) < 40)

        # delete the active doc → it leaves the tab strip
        pg.click("#wiki-delete-btn")
        pg.wait_for_timeout(300)
        pg.click("#_dy")   # confirm
        pg.wait_for_timeout(800)
        left = pg.evaluate("() => [...document.querySelectorAll('.wiki-tab')].map(t => t.dataset.path)")
        ok("deleted doc dropped from tabs", "tabtwo.md" not in left)
        ok("the other tab survives", "livetest.md" in left)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3q/tabs.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

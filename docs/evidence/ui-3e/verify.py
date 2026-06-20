"""ui-3e verify — rendered links in the live editor get custom (non-native) UI:
theme colour, a hover tooltip showing the destination, and ⌘/ctrl-click to open
(single click still enters edit mode)."""
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

        a = pg.query_selector(".cm-content a.cm-link")
        ok("link rendered as anchor", a is not None)
        if a:
            col = pg.evaluate("(el) => getComputedStyle(el).color", a)
            # accent #818cf8 → rgb(129, 140, 248); the point is it is NOT native link blue
            ok("link uses theme colour not native blue", col not in ("rgb(0, 0, 238)", "rgb(0, 0, 255)"))
            ok("link is the accent", "129, 140, 248" in col)
            # hover → url tooltip
            a.hover()
            pg.wait_for_timeout(500)
            tip = pg.query_selector("#wiki-url-tip")
            ok("hover shows a url tooltip", tip is not None)
            ok("tooltip shows the destination", tip is not None and "example.com" in (tip.inner_text() or ""))
            # cmd-click → opens (stub window.open)
            pg.evaluate("() => { window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }; }")
            a.click(modifiers=["Meta"])
            pg.wait_for_timeout(300)
            opened = pg.evaluate("() => window.__opened || []")
            ok("cmd-click opens the href", any("example.com" in u for u in opened))

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

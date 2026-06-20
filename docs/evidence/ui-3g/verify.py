"""ui-3g verify — the remaining element live-views. Fenced code becomes a shaded
block (not raw lines), inline code reads Discord-style (pill background), and the
3c-built live views (bullet/check/quote/callout/hr) are all present together."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
OPAQUE = ("rgba(0, 0, 0, 0)", "transparent")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1300})
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

        d = pg.evaluate("""() => {
          const c = document.querySelector('.cm-content');
          const cb = c.querySelector('.cm-codeblock');
          const ic = c.querySelector('.cm-code');
          return {
            codeblocks: c.querySelectorAll('.cm-codeblock').length,
            cbBg: cb ? getComputedStyle(cb).backgroundColor : null,
            cbFont: cb ? getComputedStyle(cb).fontFamily : '',
            icBg: ic ? getComputedStyle(ic).backgroundColor : null,
            bullets: c.querySelectorAll('.cm-bullet').length,
            checks: c.querySelectorAll('input[type=checkbox]').length,
            quotes: c.querySelectorAll('.cm-quote').length,
            callouts: c.querySelectorAll('.cm-callout').length,
            hrs: c.querySelectorAll('hr').length,
          };
        }""")
        ok("fenced code is a shaded block", d["codeblocks"] >= 1 and d["cbBg"] not in OPAQUE)
        ok("code block is monospace", "mono" in d["cbFont"].lower() or "JetBrains" in d["cbFont"])
        ok("inline code has a pill background", d["icBg"] not in OPAQUE and d["icBg"] is not None)
        ok("bullets present", d["bullets"] >= 2)
        ok("checkboxes present", d["checks"] >= 2)
        ok("quote present", d["quotes"] >= 1)
        ok("callout present", d["callouts"] >= 1)
        ok("hr present", d["hrs"] >= 1)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3g/live.png", full_page=True)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

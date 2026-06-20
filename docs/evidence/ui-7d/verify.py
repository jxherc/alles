"""ui-7d verify — the journal toolbar's search, export and lock controls share one height + top."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
BASE = f"http://journal.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#journal-body", state="attached", timeout=15000)
        pg.wait_for_timeout(600)
        # make sure the journal shell (with its toolbar) is shown, not a lock screen
        pg.evaluate("""async () => {
          for (const pc of ['1234','0000']) await fetch('/api/journal/lock/disable',
            {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:pc})});
          sessionStorage.removeItem('journal_token');
        }""")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#jrnl-search", state="attached", timeout=15000)
        pg.wait_for_timeout(800)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        d = pg.evaluate("""() => {
          const m = el => { const r = el.getBoundingClientRect(); return {h: Math.round(r.height), top: Math.round(r.top)}; };
          return {
            search: m(document.getElementById('jrnl-search')),
            exp: m(document.getElementById('jrnl-export')),
            lock: m(document.getElementById('jrnl-lock')),
          };
        }""")
        hs = [d["search"]["h"], d["exp"]["h"], d["lock"]["h"]]
        tops = [d["search"]["top"], d["exp"]["top"], d["lock"]["top"]]
        ok("all three controls share one height", len(set(hs)) == 1)
        ok("all three controls share one top (aligned baseline)", max(tops) - min(tops) <= 1)
        ok("height is the unified 30px", hs[0] == 30)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        print("heights:", hs, "tops:", tops)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

"""ui-8f verify — the autofill 'how to load it' link renders on its own line below the paragraph."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8878"
BASE = f"http://secrets.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-view", state="attached", timeout=15000)
        pg.wait_for_timeout(1200)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        pg.evaluate("""() => { document.getElementById('vault-pw-input').value='typemaster';
          document.getElementById('vault-unlock-btn').click(); }""")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=15000,
        )
        pg.wait_for_timeout(600)
        pg.evaluate("() => document.getElementById('vault-manage-btn').click()")
        pg.wait_for_selector("#vault-autofill-info", state="attached", timeout=10000)
        pg.wait_for_timeout(400)

        geo = pg.evaluate("""() => {
          const txt = document.querySelector('.mv-autofill-text');
          const link = document.querySelector('.mv-autofill-link');
          if (!txt || !link) return null;
          const t = txt.getBoundingClientRect(), l = link.getBoundingClientRect();
          return { linkBelow: l.top >= t.bottom - 2, sameLine: Math.abs(l.top - t.top) < 4 };
        }""")
        ok("the text paragraph and link both render", geo is not None)
        ok(
            "the 'how to load it' link sits on its own line below the text",
            geo and geo["linkBelow"] and not geo["sameLine"],
        )

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

"""ui-8d verify — Watchtower is explained, lays out in sections, and is a real toggle: the button
indicates active when open and a second click hides it."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8877"
BASE = f"http://secrets.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-view", state="attached", timeout=15000)
        pg.wait_for_timeout(1200)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        pg.evaluate("""() => { document.getElementById('vault-pw-input').value='wtmaster';
          document.getElementById('vault-unlock-btn').click(); }""")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=15000,
        )
        pg.wait_for_timeout(600)

        # open watchtower
        pg.evaluate("() => document.getElementById('vault-watchtower-btn').click()")
        pg.wait_for_selector("#vault-wt", state="attached", timeout=10000)
        pg.wait_for_timeout(400)
        opened = pg.evaluate("""() => ({
          shown: !!document.getElementById('vault-wt'),
          btnActive: document.getElementById('vault-watchtower-btn').classList.contains('active'),
          intro: (document.querySelector('.wt-intro')?.innerText || ''),
          sections: document.querySelectorAll('.wt-section').length,
          sectionDescs: document.querySelectorAll('.wt-desc').length,
          backIcon: !!document.querySelector('#wt-back svg.ic'),
        })""")
        ok("watchtower panel opens", opened["shown"])
        ok("the watchtower button indicates active when open", opened["btnActive"])
        ok(
            "a one-line explanation of Watchtower is shown",
            "scans your saved passwords" in opened["intro"],
        )
        ok("breached / reused / weak sections render", opened["sections"] == 3)
        ok("each section has its own explainer", opened["sectionDescs"] == 3)
        ok("back button uses an icon", opened["backIcon"])

        # click the watchtower button AGAIN → it toggles closed
        pg.evaluate("() => document.getElementById('vault-watchtower-btn').click()")
        pg.wait_for_timeout(500)
        closed = pg.evaluate("""() => ({
          gone: !document.getElementById('vault-wt'),
          btnActive: document.getElementById('vault-watchtower-btn').classList.contains('active'),
          backToEntries: !!document.getElementById('vault-entry-list'),
        })""")
        ok("re-clicking the button hides the watchtower panel", closed["gone"])
        ok("the button is no longer indicated active", not closed["btnActive"])
        ok("the vault entry list is back", closed["backToEntries"])

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

"""ui-8a verify — vault toolbar: unified icons, switcher reads as a chip, settings (gear) is rightmost."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
BASE = f"http://secrets.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
GLYPHS = "✈⚙🛡🔓＋"


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-view", state="attached", timeout=15000)
        pg.wait_for_timeout(1500)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        # unlock (first unlock sets the master)
        pg.evaluate("""() => {
          document.getElementById('vault-pw-input').value = 'test1234';
          document.getElementById('vault-unlock-btn').click();
        }""")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=15000,
        )
        pg.wait_for_timeout(1200)

        d = pg.evaluate("""() => {
          const head = document.querySelector('#vault-view .page-view-head');
          const shown = [...head.querySelectorAll('button')].filter(b => getComputedStyle(b).display !== 'none');
          const manage = document.getElementById('vault-manage-btn');
          const sw = document.getElementById('vault-switcher');
          return {
            order: shown.map(b => b.id),
            manageLast: shown.length && shown[shown.length - 1].id === 'vault-manage-btn',
            manageSvg: !!(manage && manage.querySelector('svg.ic')),
            iconBtns: ['vault-travel-btn','vault-bio-add-btn','vault-watchtower-btn','vault-manage-btn']
              .every(id => { const b = document.getElementById(id); return b && b.querySelector('svg.ic'); }),
            switcherChip: !!(sw && sw.classList.contains('vault-switcher')),
            headText: head.innerText,
          };
        }""")
        ok("settings (gear) is the rightmost toolbar button", d["manageLast"])
        ok("settings button renders an svg icon", d["manageSvg"])
        ok("travel/biometric/watchtower/settings all render icons", d["iconBtns"])
        ok("switcher carries the chip class", d["switcherChip"])
        ok("no emoji glyphs in the vault toolbar", not any(g in d["headText"] for g in GLYPHS))

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        print("toolbar order:", d["order"])
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

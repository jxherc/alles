"""ui-8e verify — the visual custom-type editor: build a "Wi-Fi" type with two fields (one half-width,
one secret), then add a secret of that type and confirm the form renders the custom fields."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8877"
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

        # open settings → custom-type editor
        pg.evaluate("() => document.getElementById('vault-manage-btn').click()")
        pg.wait_for_selector("#mv-types", state="attached", timeout=10000)
        pg.wait_for_timeout(400)
        hasEditor = pg.evaluate("() => !!document.getElementById('vt-new')")
        ok("settings has a custom-type editor", hasEditor)

        # build a new type
        pg.evaluate("() => document.getElementById('vt-new').click()")
        pg.wait_for_selector("#vt-label", state="attached", timeout=8000)
        pg.evaluate("""() => {
          document.getElementById('vt-label').value = 'Wi-Fi';
          // field 0: 'network' at half width
          document.querySelector('.vt-flabel[data-i="0"]').value = 'network';
          document.querySelector('.vt-width[data-i="0"] .seg-opt[data-w="half"]').click();
        }""")
        # add a second field
        pg.evaluate("() => document.getElementById('vt-addf').click()")
        pg.wait_for_selector('.vt-flabel[data-i="1"]', state="attached", timeout=8000)
        pg.evaluate("""() => {
          document.querySelector('.vt-flabel[data-i="1"]').value = 'passphrase';
          document.querySelector('.vt-kind[data-i="1"] .seg-opt[data-kd="secret"]').click();
        }""")
        pg.evaluate("() => document.getElementById('vt-save').click()")
        pg.wait_for_timeout(700)

        saved = pg.evaluate("""() => {
          const rows = [...document.querySelectorAll('.vt-row')].map(r => r.querySelector('.vt-name').textContent);
          return { rows, has: rows.includes('Wi-Fi') };
        }""")
        ok("the new 'Wi-Fi' type is listed", saved["has"])

        # close settings, open the add-secret form, switch to the custom type
        pg.evaluate("() => document.getElementById('mv-close').click()")
        pg.wait_for_timeout(300)
        pg.evaluate("() => document.getElementById('vault-new-btn').click()")
        pg.wait_for_selector("#vf-type", state="attached", timeout=8000)
        pg.wait_for_timeout(300)
        opts = pg.evaluate("() => document.getElementById('vf-type').dataset.options || ''")
        ok("the secret form's type picker lists the custom type", "Wi-Fi" in opts)

        fields = pg.evaluate("""() => {
          const sel = document.getElementById('vf-type');
          sel.value = 'wi_fi';
          sel.dispatchEvent(new Event('change'));
          const labels = [...document.querySelectorAll('#vf-fields label')].map(l => l.textContent);
          return labels;
        }""")
        ok(
            "selecting the custom type renders its fields",
            "network" in fields and "passphrase" in fields,
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

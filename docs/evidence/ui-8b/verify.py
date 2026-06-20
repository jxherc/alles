"""ui-8b verify — main vault vs per-vault passwords: the manage panel shows a main badge + helper,
renames inline, and changes a vault's password (re-key) live."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
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

        # unlock with a known master
        pg.evaluate("""() => {
          document.getElementById('vault-pw-input').value = 'mainpw99';
          document.getElementById('vault-unlock-btn').click();
        }""")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=15000,
        )
        pg.wait_for_timeout(800)

        # open settings (manage) → the vault list with badges
        pg.evaluate("() => document.getElementById('vault-manage-btn').click()")
        pg.wait_for_selector("#mv-list .mv-row", state="attached", timeout=10000)
        pg.wait_for_timeout(500)

        m = pg.evaluate("""() => {
          const rows = [...document.querySelectorAll('#mv-list .mv-row')];
          const main = rows[0];
          return {
            mainBadge: !!main.querySelector('.mv-badge.mv-main'),
            mainBadgeText: main.querySelector('.mv-badge')?.textContent || '',
            chpwText: main.querySelector('[data-chpw]')?.textContent || '',
            hasHelp: !!document.querySelector('#mv-list .mv-help'),
            renameable: !!main.querySelector('.mv-name[data-rename]'),
          };
        }""")
        ok("main vault shows a 'main' badge", m["mainBadge"] and m["mainBadgeText"] == "main")
        ok("main vault offers 'change master password'", "master password" in m["chpwText"])
        ok("manage panel explains the main/per-vault model", m["hasHelp"])
        ok("vault name is click-to-rename", m["renameable"])

        # inline-rename the main vault
        renamed = pg.evaluate("""async () => {
          const span = document.querySelector('#mv-list .mv-name[data-rename]');
          span.click();
          await new Promise(r => setTimeout(r, 200));
          const inp = document.querySelector('.mv-rename-input');
          inp.value = 'Vault Prime';
          inp.dispatchEvent(new Event('input'));
          inp.blur();
          await new Promise(r => setTimeout(r, 600));
          const v = await fetch('/api/vault/vaults', {headers:{'X-Vault-Token': sessionStorage.getItem('vault_token') || ''}}).then(r=>r.json()).catch(()=>[]);
          return document.querySelector('#mv-list .mv-name')?.textContent || '';
        }""")
        ok("inline rename updates the name", renamed == "Vault Prime")

        # change the master password (re-key), then confirm the new one unlocks and old doesn't
        chg = pg.evaluate("""async () => {
          document.querySelector('[data-chpw]').click();
          await new Promise(r => setTimeout(r, 250));
          document.getElementById('np-1').value = 'mainpw2';
          document.getElementById('np-2').value = 'mainpw2';
          document.getElementById('np-ok').click();
          await new Promise(r => setTimeout(r, 700));
          const oldR = await fetch('/api/vault/unlock', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({password:'mainpw99'})});
          const newR = await fetch('/api/vault/unlock', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({password:'mainpw2'})});
          return { oldStatus: oldR.status, newStatus: newR.status };
        }""")
        ok("after change, the old master no longer unlocks", chg["oldStatus"] == 401)
        ok("after change, the new master unlocks", chg["newStatus"] == 200)

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

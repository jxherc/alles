"""ui-7b verify — CardDAV moved off the toolbar into the contacts settings cog, which opens a real
settings pane with a connect/sync/disconnect flow and an auto-sync interval control that persists."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
BASE = f"http://contacts.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#contacts-view", state="attached", timeout=15000)
        pg.wait_for_timeout(700)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        chrome = pg.evaluate("""() => ({
          toolbarBtn: !!document.getElementById('contacts-carddav-btn'),
          cog: !!document.querySelector('.app-cog[data-app="contacts"]'),
        })""")
        ok("CardDAV button removed from the toolbar", not chrome["toolbarBtn"])
        ok("contacts settings cog present", chrome["cog"])

        # open the cog → the per-app settings popover with a CardDAV action
        pop = pg.evaluate("""async () => {
          document.querySelector('.app-cog[data-app="contacts"]').click();
          await new Promise(r => setTimeout(r, 300));
          const p = document.querySelector('.app-settings-pop');
          const act = p ? [...p.querySelectorAll('.aps-action')].find(b => b.dataset.act === '_contactsCardDav') : null;
          return { open: !!p, hasAction: !!act };
        }""")
        ok("settings popover opens", pop["open"])
        ok("popover has a CardDAV action", pop["hasAction"])

        # click the CardDAV action → the reworked pane with status, actions, interval seg
        pane = pg.evaluate("""async () => {
          [...document.querySelectorAll('.aps-action')].find(b => b.dataset.act === '_contactsCardDav').click();
          await new Promise(r => setTimeout(r, 400));
          const panel = document.querySelector('.carddav-panel');
          return {
            shown: !!panel,
            hasStatus: !!document.getElementById('cdav-status'),
            hasConnect: !!document.getElementById('cdav-connect'),
            hasInterval: !!document.getElementById('cdav-interval'),
            ivOpts: panel ? [...document.querySelectorAll('#cdav-interval .seg-opt')].map(o => o.dataset.val) : [],
            backIcon: !!document.querySelector('#cdav-back svg.ic'),
          };
        }""")
        ok("CardDAV settings pane shows", pane["shown"])
        ok(
            "pane has status + connect + interval",
            pane["hasStatus"] and pane["hasConnect"] and pane["hasInterval"],
        )
        ok("interval offers off/hourly/daily", pane["ivOpts"] == ["off", "hourly", "daily"])
        ok("back button uses an icon", pane["backIcon"])

        # pick 'daily' → it persists to the backend
        saved = pg.evaluate("""async () => {
          document.querySelector('#cdav-interval .seg-opt[data-val="daily"]').click();
          await new Promise(r => setTimeout(r, 400));
          const st = await fetch('/api/carddav/status').then(r => r.json());
          const active = document.querySelector('#cdav-interval .seg-opt.active')?.dataset.val;
          return { stored: st.interval, active };
        }""")
        ok("selecting daily marks it active", saved["active"] == "daily")
        ok("interval persisted to the backend", saved["stored"] == "daily")

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

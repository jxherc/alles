"""ui-4e verify — rules + accounts left the toolbar for mail settings; the settings
action buttons open the existing panels."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://mail.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1300, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-search", state="attached", timeout=15000)
        pg.wait_for_timeout(2400)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("rules button gone from toolbar", pg.query_selector("#mail-rules-btn") is None)
        ok("accounts button gone from toolbar", pg.query_selector("#mail-accounts-btn") is None)

        # open mail settings → has accounts + rules action buttons
        pg.evaluate("() => document.querySelector(\".app-cog[data-app='mail']\")?.click()")
        pg.wait_for_timeout(500)
        d = pg.evaluate("""() => {
          const pop = document.querySelector('.app-settings-pop');
          if (!pop) return {pop:false};
          const acts = [...pop.querySelectorAll('.aps-action')].map(a => ({t:a.textContent, act:a.dataset.act}));
          return {pop:true, acts};
        }""")
        ok("mail settings popup opens", d["pop"])
        ok("settings has an accounts action", any(a["act"] == "_mailAccounts" for a in d.get("acts", [])))
        ok("settings has a rules action", any(a["act"] == "_mailRules" for a in d.get("acts", [])))

        # clicking the accounts action opens the accounts panel (and closes the popover)
        pg.evaluate("""() => { window._mailAccounts = () => { window.__acctOpened = true; };
          document.querySelector(\".aps-action[data-act='_mailAccounts']\").click(); }""")
        pg.wait_for_timeout(300)
        ok("accounts action runs the hook + closes the popover",
           pg.evaluate("() => window.__acctOpened === true") and pg.query_selector(".app-settings-pop") is None)

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

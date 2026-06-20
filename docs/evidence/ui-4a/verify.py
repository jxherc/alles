"""ui-4a verify — mail toolbar cleanup: live search (no Enter needed), threads button
gone (moved to settings), compose is the rightmost action."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://mail.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    searched = {"n": 0}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1300, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.route("**/api/mail/search**", lambda route: (
            searched.update(n=searched["n"] + 1) or route.fulfill(status=200, content_type="application/json", body='{"messages":[]}')))
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-search", state="attached", timeout=15000)
        pg.wait_for_timeout(2600)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const acts = [...document.querySelectorAll('.mail-head-actions .btn')].map(b => b.id);
          return {
            threads: !!document.querySelector('#mail-threads-btn'),
            placeholder: document.querySelector('#mail-search')?.getAttribute('placeholder') || '',
            actions: acts,
            composeLast: acts[acts.length - 1] === 'mail-compose-btn',
          };
        }""")
        ok("threads button removed", not d["threads"])
        ok("search placeholder dropped the '(enter)'", "enter" not in d["placeholder"].lower() and "search mail" in d["placeholder"])
        ok("compose is the rightmost action", d["composeLast"])

        # live search: type without pressing Enter → searchMail runs (renders its result/empty state)
        pg.evaluate("""() => {
          const s = document.querySelector('#mail-search');
          s.value = 'invoicexyz';
          s.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        pg.wait_for_timeout(700)
        listed = pg.evaluate("() => (document.querySelector('#mail-list')?.textContent || '')")
        ok("typing triggers a live search (no Enter)", "invoicexyz" in listed or "searching" in listed.lower())

        # mail settings cog has the conversation-grouping toggle
        pg.evaluate("() => document.querySelector(\".app-cog[data-app='mail']\")?.click()")
        pg.wait_for_timeout(500)
        seg = pg.evaluate("""() => {
          const pop = document.querySelector('.app-settings-pop');
          if (!pop) return {pop:false};
          return {pop:true, threadsField: !!pop.querySelector('.seg[data-k=\"mail_threads\"]'), txt: pop.innerText.toLowerCase()};
        }""")
        ok("mail settings popup opens", seg["pop"])
        ok("grouping moved into settings", seg.get("threadsField") and "conversation" in seg.get("txt", ""))

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-4a/toolbar.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

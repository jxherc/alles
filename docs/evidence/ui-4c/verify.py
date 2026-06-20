"""ui-4c verify — account picker on the left, search centered with a cap, and an
'all inboxes' option for multiple accounts."""
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
        pg.wait_for_timeout(2600)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const head = document.querySelector('.mail-head');
          const kids = [...head.children];
          const idx = sel => kids.findIndex(k => k.matches(sel) || k.querySelector?.(sel));
          const search = document.querySelector('#mail-search');
          const cs = getComputedStyle(search);
          return {
            accountBeforeSearch: idx('#mail-account') < idx('#mail-search'),
            searchBeforeActions: idx('#mail-search') < idx('.mail-head-actions'),
            accountFirstish: idx('#mail-account') <= 1,
            maxW: cs.maxWidth,
            marginL: cs.marginLeft,
            marginR: cs.marginRight,
            grows: cs.flexGrow,
          };
        }""")
        ok("account picker is left of the search", d["accountBeforeSearch"])
        ok("account sits at the left of the head", d["accountFirstish"])
        ok("search is before the right-hand actions", d["searchBeforeActions"])
        ok("search has a sensible max-width cap", d["maxW"] == "560px")
        ok("search is centered (auto side margins)", d["marginL"] == "auto" and d["marginR"] == "auto")
        ok("search grows to fill the middle", float(d["grows"]) >= 1)

        # with no real accounts we can only confirm the control exists here; the 'all inboxes'
        # option logic (_accounts.length > 1) is covered by the gate test
        ok("account dropdown control present", pg.query_selector("#mail-account") is not None)

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

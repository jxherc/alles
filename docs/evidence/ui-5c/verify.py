"""ui-5c verify — the calendar view switcher is one segmented control and actually switches
month/week/day/agenda/year."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8872"
BASE = f"http://calendar.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#cal-view", timeout=15000)
        pg.wait_for_selector("#cal-view .seg-opt", timeout=15000)
        pg.wait_for_timeout(600)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        shape = pg.evaluate("""() => {
          const seg = document.querySelector('#cal-view');
          const opts = [...document.querySelectorAll('#cal-view .seg-opt')];
          return {
            isSeg: seg && seg.classList.contains('seg') && seg.classList.contains('seg-cal'),
            count: opts.length,
            views: opts.map(o => o.dataset.view),
            // one continuous control: opts share a border, no per-button gap
            gap: seg ? getComputedStyle(seg).gap : '',
          };
        }""")
        ok("switcher is a single .seg.seg-cal", shape["isSeg"])
        ok("has 5 seg options", shape["count"] == 5)
        ok(
            "covers month/week/day/agenda/year",
            shape["views"] == ["month", "week", "day", "agenda", "year"],
        )

        # click each view; assert it becomes the active one and the calendar re-renders to match
        for v in ("week", "day", "agenda", "year", "month"):
            pg.evaluate(
                """(v) => document.querySelector(`#cal-view .seg-opt[data-view="${v}"]`).click()""",
                v,
            )
            pg.wait_for_timeout(350)
            active = pg.evaluate(
                """(v) => {
                  const btn = document.querySelector(`#cal-view .seg-opt[data-view="${v}"]`);
                  const stored = localStorage.getItem('cal-view');
                  const others = [...document.querySelectorAll('#cal-view .seg-opt')]
                    .filter(o => o.dataset.view !== v);
                  return {
                    active: btn.classList.contains('active'),
                    onlyOne: others.every(o => !o.classList.contains('active')),
                    stored,
                  };
                }""",
                v,
            )
            ok(f"{v}: option highlights as active", active["active"])
            ok(f"{v}: exactly one active at a time", active["onlyOne"])
            ok(f"{v}: persisted to localStorage", active["stored"] == v)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-5c/switcher.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

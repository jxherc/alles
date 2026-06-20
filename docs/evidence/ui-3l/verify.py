"""ui-3l verify — the version-history panel reads cleanly: padded, aligned rows with
when/size and diff/restore, and a readable diff block."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1000)
        # create a revision: save an edited body (snapshots the pre-change state)
        pg.evaluate("""async () => {
          await fetch('/api/vault-md/file', {method:'PUT', headers:{'content-type':'application/json'},
            body: JSON.stringify({path:'livetest.md', content:'edited body for a new revision'})});
        }""")
        pg.wait_for_timeout(400)
        pg.click("#wiki-history-btn")
        pg.wait_for_timeout(800)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const h = document.querySelector('#wiki-history');
          const cs = h ? getComputedStyle(h) : null;
          const row = h && h.querySelector('.wiki-rev-row');
          return {
            shown: !!(h && h.style.display !== 'none'),
            padL: cs ? cs.paddingLeft : '0px',
            width: cs ? parseInt(cs.width) : 0,
            rows: h ? h.querySelectorAll('.wiki-rev').length : 0,
            hasWhen: !!(row && row.querySelector('.wiki-rev-when')),
            hasBtns: row ? row.querySelectorAll('.wiki-rev-btn').length : 0,
            label: !!(h && h.querySelector('.wiki-rev-label')),
          };
        }""")
        ok("history panel shown", d["shown"])
        ok("panel is padded", d["padL"] not in ("0px", ""))
        ok("panel is roomy (>=260px)", d["width"] >= 260)
        ok("has a 'version history' label", d["label"])
        ok("at least one revision row", d["rows"] >= 1)
        ok("row shows a timestamp", d["hasWhen"])
        ok("row has diff + restore buttons", d["hasBtns"] == 2)
        # open the diff
        pg.eval_on_selector("#wiki-history [data-rev-diff]", "el => el.click()")
        pg.wait_for_timeout(700)
        ok("diff renders in a readable block", pg.query_selector("#wiki-history .wiki-rev-diff-pre") is not None)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3l/history.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

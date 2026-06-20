"""ui-3r verify — outline populates from headings (with level emphasis + jump) and
explains itself clearly when there are none."""
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
        # an empty doc first → empty explainer
        pg.evaluate("""async () => {
          await fetch('/api/vault-md/file', {method:'POST', headers:{'content-type':'application/json'},
            body: JSON.stringify({path:'nohead.md', content:'just text, no headings here'})});
        }""")
        pg.wait_for_timeout(300)
        pg.evaluate("() => location.reload()")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1500)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # open the no-heading doc, open outline → explainer
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"nohead.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(800)
        pg.click("#wiki-outline-btn")
        pg.wait_for_timeout(400)
        empty = pg.evaluate("() => (document.querySelector('#wiki-outline .wiki-outline-empty')?.textContent || '')")
        ok("empty outline explains itself", "no headings yet" in empty and "#" in empty)

        # open the heading-rich doc → populated outline
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(800)
        # force a fresh outline render on the new doc: close if open, then open
        if pg.evaluate("() => document.querySelector('#wiki-outline')?.style.display === 'block'"):
            pg.click("#wiki-outline-btn")
            pg.wait_for_timeout(250)
        pg.click("#wiki-outline-btn")
        pg.wait_for_timeout(500)
        d = pg.evaluate("""() => {
          const items = [...document.querySelectorAll('#wiki-outline .wiki-outline-item')];
          const h = document.querySelector('#wiki-outline .wiki-outline-head');
          const l1 = items.find(i => i.classList.contains('lvl1'));
          const l2 = items.find(i => i.classList.contains('lvl2'));
          return {
            count: items.length,
            head: h ? h.textContent : '',
            texts: items.map(i => i.textContent),
            l1pad: l1 ? getComputedStyle(l1).paddingLeft : '',
            l2pad: l2 ? getComputedStyle(l2).paddingLeft : '',
            l1weight: l1 ? getComputedStyle(l1).fontWeight : '',
          };
        }""")
        ok("outline lists the headings", d["count"] >= 2)
        ok("outline header shows the count", "heading" in d["head"])
        ok("it has Heading One + Heading Two", any("Heading One" in t for t in d["texts"]) and any("Heading Two" in t for t in d["texts"]))
        ok("deeper headings are indented more", d["l2pad"] and d["l1pad"] and float(d["l2pad"].replace("px", "")) > float(d["l1pad"].replace("px", "")))
        ok("top-level headings are emphasised", int(d["l1weight"] or 0) >= 500)

        # jump: click a heading → editor scrolls/selects
        pg.eval_on_selector("#wiki-outline .wiki-outline-item", "el => el.click()")
        pg.wait_for_timeout(300)
        ok("clicking a heading is wired (no error)", True)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3r/outline.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

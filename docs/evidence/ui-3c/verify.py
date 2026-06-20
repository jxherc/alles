"""ui-3c verify — every markdown element renders in docs live mode.
Run against an isolated server seeded with livetest.md:
  ALLES_DATA=<abs>/.tmp_3c PORT=8871 AUTH_ENABLED=false python app.py
  python docs/evidence/ui-3c/verify.py 8871
Exits non-zero (and prints FAIL lines) until the live-preview engine renders each element."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1500})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1400)
        # park the cursor on the title line (line 1) so nothing below it is "active"/revealed
        pg.evaluate("""() => { const v = window._cmEditor?.view; if (v) v.dispatch({selection:{anchor:0}}); }""")
        pg.wait_for_timeout(700)
        d = pg.evaluate("""() => {
          const c = document.querySelector('.cm-content');
          const imgs = [...c.querySelectorAll('img')].map(i => i.getAttribute('src') || '');
          const links = [...c.querySelectorAll('a')].map(a => ({t: a.textContent, h: a.getAttribute('href')}));
          return {
            imgs,
            tables: c.querySelectorAll('table').length,
            checkboxes: c.querySelectorAll('input[type=checkbox]').length,
            checked: c.querySelectorAll('input[type=checkbox]:checked').length,
            callouts: c.querySelectorAll('.cm-callout').length,
            hrs: c.querySelectorAll('hr').length,
            bullets: c.querySelectorAll('.cm-bullet').length,
            marks: c.querySelectorAll('.cm-mark').length,
            links,
            text: c.innerText,
          };
        }""")

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("two images render (md + wiki-embed)", len([s for s in d["imgs"] if s]) >= 2)
        ok("wiki-embed image uses raw route", any("/api/vault-md/raw?path=" in s for s in d["imgs"]))
        ok("table renders", d["tables"] >= 1)
        ok("two checkboxes render", d["checkboxes"] >= 2)
        ok("one checkbox is checked", d["checked"] >= 1)
        ok("callout renders", d["callouts"] >= 1)
        ok("hr renders", d["hrs"] >= 1)
        ok("bullets render as markers", d["bullets"] >= 2)
        ok("highlight renders", d["marks"] >= 1)
        link = next((l for l in d["links"] if l["h"] and "example.com" in l["h"]), None)
        ok("link is an anchor with href", link is not None)
        ok("link text shown, url hidden", link is not None and "example.com" not in (link["t"] or "")
            and "url" not in d["text"].lower().split("example")[0][-40:] if link else False)
        ok("raw pipes gone from live text", "| Name | Role |" not in d["text"])
        ok("raw ![[ ]] gone from live text", "![[" not in d["text"])

        real_errs = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real_errs)
        if real_errs:
            print("ERRORS:", real_errs)
        b.close()

    print("\n=== probe ===")
    print(d if "d" in dir() else "no data")
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

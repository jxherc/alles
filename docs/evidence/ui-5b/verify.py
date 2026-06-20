"""ui-5b verify — the files app draws its controls from the central icon set (real <svg class=ic>),
no leftover emoji/Unicode glyphs."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8872"
BASE = f"http://files.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
GLYPHS = "🕘🖼📦📈🧬🗑☆★⇗💬⏱⊙✎✕↩☰▦✓○🎉"


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 850})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#files-view", state="attached", timeout=15000)
        pg.wait_for_timeout(800)

        # seed a file so a real row (with hover actions) renders
        st = pg.evaluate("""async () => {
          const fd = new FormData();
          fd.append('file', new Blob(['hello 5b'], {type:'text/plain'}), 'note5b.txt');
          const r = await fetch('/api/files/upload', {method:'POST', body: fd});
          return r.status;
        }""")
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#files-view", state="attached", timeout=15000)
        pg.wait_for_selector(".file-row", state="attached", timeout=15000)
        pg.wait_for_timeout(800)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        d = pg.evaluate("""() => {
          const view = document.querySelector('#files-view');
          const smart = [...document.querySelectorAll('.files-smart')];
          const acts = [...document.querySelectorAll('.file-row .file-act')];
          const star = document.querySelector('.file-star');
          return {
            smartCount: smart.length,
            smartAllSvg: smart.length > 0 && smart.every(b => b.querySelector('svg.ic')),
            actCount: acts.length,
            actAllSvg: acts.length > 0 && acts.every(a => a.querySelector('svg.ic')),
            starHasSvg: !!(star && star.querySelector('svg.ic')),
            text: view ? view.innerText : '',
          };
        }""")
        ok("upload seeded a file (200)", st == 200)
        ok("smart-folder bar rendered", d["smartCount"] >= 6)
        ok("every smart folder shows an svg icon", d["smartAllSvg"])
        ok("row hover actions rendered", d["actCount"] >= 5)
        ok("every row action shows an svg icon", d["actAllSvg"])
        ok("star action is an svg icon", d["starHasSvg"])
        leftover = [g for g in GLYPHS if g in d["text"]]
        ok("no emoji/unicode glyphs in the files view", not leftover)
        if leftover:
            print("LEFTOVER GLYPHS:", leftover)

        # star toggle swaps to a filled star icon
        toggled = pg.evaluate("""async () => {
          const star = document.querySelector('.file-star');
          if (!star) return null;
          star.click();
          await new Promise(r => setTimeout(r, 400));
          const svg = star.querySelector('svg.ic');
          return svg ? svg.innerHTML.includes('fill="currentColor"') : false;
        }""")
        ok("clicking star renders the filled (star-fill) icon", toggled is True)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-5b/smart.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

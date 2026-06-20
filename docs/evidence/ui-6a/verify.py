"""ui-6a verify — gallery header controls share one size, lightbox lays out as a tidy 2-col grid.
Gallery is account-gated (hidden on this server), so we read computed styles via the DOM."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8872"
BASE = f"http://gallery.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#photos-view", state="attached", timeout=15000)
        pg.wait_for_timeout(800)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        d = pg.evaluate("""() => {
          const head = document.querySelector('.photos-head');
          const btns = [...head.querySelectorAll('.btn')];
          const sizes = new Set(btns.map(b => getComputedStyle(b).fontSize));
          const trash = document.querySelector('#photos-trash-btn');
          // force the lightbox visible to read its (otherwise display:none) layout
          const lb = document.querySelector('#photos-lightbox');
          lb.style.display = 'flex';
          const side = document.querySelector('.photos-lightbox-side');
          const acts = document.querySelector('.photos-lightbox-actions');
          const sw = parseFloat(getComputedStyle(side).width);
          const cols = getComputedStyle(acts).gridTemplateColumns.split(' ').filter(Boolean).length;
          lb.style.display = 'none';
          return {
            btnCount: btns.length,
            oneSize: sizes.size === 1,
            theSize: [...sizes][0],
            inlineFont: btns.some(b => b.getAttribute('style') && b.getAttribute('style').includes('font-size')),
            trashClass: !!(trash && trash.classList.contains('photos-trash')),
            sideW: sw,
            actCols: cols,
          };
        }""")
        ok("header has its control buttons", d["btnCount"] >= 5)
        ok("every header control shares one font-size", d["oneSize"])
        ok("no leftover inline font-size on controls", not d["inlineFont"])
        ok("trash carries the .photos-trash (margin-left:auto) class", d["trashClass"])
        ok("lightbox side panel widened (>=260px)", d["sideW"] >= 260)
        ok("lightbox actions render as a 2-column grid", d["actCols"] == 2)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        print("header control font-size:", d["theSize"], "| side width:", d["sideW"])
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

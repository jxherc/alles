"""ui-6b verify — the gallery draws its controls from the central icon set: header buttons, the
favorite badge on cells, and every lightbox action render real <svg class=ic>, no emoji."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8872"
BASE = f"http://gallery.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
GLYPHS = "🔗✨🗑♥♡▶🔒🗺📍★↩"


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#photos-view", state="attached", timeout=15000)
        pg.wait_for_timeout(700)

        # seed one photo so cells + lightbox exist
        st = pg.evaluate("""async () => {
          const cv = document.createElement('canvas'); cv.width = 8; cv.height = 8;
          cv.getContext('2d').fillRect(0, 0, 8, 8);
          const blob = await new Promise(r => cv.toBlob(r, 'image/png'));
          const fd = new FormData(); fd.append('file', blob, 'verify6b.png');
          return (await fetch('/api/photos/upload', {method: 'POST', body: fd})).status;
        }""")
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#photos-view", state="attached", timeout=15000)
        pg.wait_for_selector(".photos-cell", state="attached", timeout=15000)
        pg.wait_for_timeout(700)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        head = pg.evaluate("""() => {
          const ids = ['photos-share-album-btn', 'photos-gen-btn', 'photos-trash-btn'];
          const btns = ids.map(i => document.getElementById(i));
          const album = document.getElementById('photos-album');
          return {
            allSvg: btns.every(b => b && b.querySelector('svg.ic')),
            headText: document.querySelector('.photos-head').innerText,
            albumOpts: album ? (album.dataset.options || '') : '',
          };
        }""")
        ok("upload seeded a photo", st == 200)
        ok("header share/generate/trash render svg icons", head["allSvg"])
        ok("no emoji text in the gallery header", not any(g in head["headText"] for g in GLYPHS))
        ok(
            "album dropdown options carry no emoji labels",
            not any(g in head["albumOpts"] for g in GLYPHS),
        )

        # open the lightbox on the seeded cell, check every action is an icon button
        lb = pg.evaluate("""async () => {
          document.querySelector('.photos-cell').click();
          await new Promise(r => setTimeout(r, 500));
          const ids = ['photos-fav-btn', 'photos-hide-btn', 'photos-edit-btn',
                       'photos-dl-btn', 'photos-del-btn', 'photos-close-btn'];
          const btns = ids.map(i => document.getElementById(i));
          const open = getComputedStyle(document.querySelector('#photos-lightbox')).display !== 'none';
          return {
            open,
            allSvg: btns.every(b => b && b.querySelector('svg.ic')),
            missing: ids.filter(i => { const b = document.getElementById(i); return !(b && b.querySelector('svg.ic')); }),
          };
        }""")
        ok("lightbox opened", lb["open"])
        ok("every lightbox action is an icon button", lb["allSvg"])
        if lb["missing"]:
            print("  missing icons on:", lb["missing"])

        # favorite from the lightbox → the cell gets the heart-icon badge
        fav = pg.evaluate("""async () => {
          document.getElementById('photos-fav-btn').click();
          await new Promise(r => setTimeout(r, 500));
          const badge = document.querySelector('.photos-cell .photos-fav-badge svg.ic');
          const favBtnSvg = document.querySelector('#photos-fav-btn svg.ic');
          return { badge: !!badge, favBtnIcon: !!favBtnSvg };
        }""")
        ok("favoriting renders the heart badge icon on the cell", fav["badge"])
        ok("favorite button shows an icon", fav["favBtnIcon"])

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-6b/lightbox.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()

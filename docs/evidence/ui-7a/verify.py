"""ui-7a verify — contacts header is de-iconed + aligned, list rows use the rebuilt aligned layout
with icon stars, detail back/me use icons. Contacts is account-gated so we read the DOM."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8872"
BASE = f"http://contacts.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
GLYPHS = "★☆🎂📍✓←"


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#contacts-view", state="attached", timeout=15000)
        pg.wait_for_timeout(600)
        pg.evaluate("""async () => {
          const cs = [['Ada Lovelace','ada@x.com','555-0100','Engines'],
                      ['Grace Hopper','grace@x.com','555-0222','Navy']];
          for (const [name,email,phone,company] of cs)
            await fetch('/api/contacts',{method:'POST',headers:{'content-type':'application/json'},
              body:JSON.stringify({name,email,phone,company})});
        }""")
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#contacts-view", state="attached", timeout=15000)
        pg.wait_for_selector(".contact-item", state="attached", timeout=15000)
        pg.wait_for_timeout(600)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        d = pg.evaluate("""() => {
          const fav = document.getElementById('contacts-fav-filter');
          const bday = document.getElementById('contacts-bday-btn');
          const rows = [...document.querySelectorAll('.contact-item')];
          const r0 = rows[0];
          return {
            favText: fav ? fav.textContent.trim() : '',
            bdayText: bday ? bday.textContent.trim() : '',
            rowCount: rows.length,
            hasMain: !!(r0 && r0.querySelector('.contact-rowmain')),
            hasActs: !!(r0 && r0.querySelector('.contact-rowacts')),
            starSvg: !!(r0 && r0.querySelector('.contact-star svg.ic')),
            listText: document.getElementById('contacts-list').innerText,
          };
        }""")
        ok("fav filter is a text label (no star glyph)", d["favText"] == "favorites")
        ok("birthdays is a text label (no cake glyph)", d["bdayText"] == "birthdays")
        ok("contacts rows rendered", d["rowCount"] >= 2)
        ok("rows use the rebuilt main/actions layout", d["hasMain"] and d["hasActs"])
        ok("per-row star is an svg icon", d["starSvg"])
        ok("no emoji glyphs in the contacts list", not any(g in d["listText"] for g in GLYPHS))

        # open a contact → detail back + photo + name + me button, with icons on back
        det = pg.evaluate("""async () => {
          document.querySelector('[data-open]').click();
          await new Promise(r => setTimeout(r, 500));
          const back = document.getElementById('cd-back');
          return {
            opened: !!document.querySelector('.contact-detail'),
            backIcon: !!(back && back.querySelector('svg.ic')),
            backText: back ? back.textContent.trim() : '',
          };
        }""")
        ok("contact detail opens", det["opened"])
        ok("detail back button uses an icon", det["backIcon"])
        ok("detail back reads 'contacts' (no arrow glyph)", "←" not in det["backText"])

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

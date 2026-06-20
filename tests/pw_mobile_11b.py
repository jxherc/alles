"""11b-1 — responsive phone layout. At a 390px phone width the aide sidebar would otherwise
eat ~64% of the screen; now it's an off-canvas drawer (closed by default, opens over a backdrop)
and nothing overflows horizontally. iPhone-12-ish viewport (390x844).

Drives aide.localhost:8879. ALLES_DATA=.tmp_11b3 PORT=8879 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8879"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "11b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        pg = ctx.new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".app", timeout=15000)
        pg.wait_for_selector('.nav-item[data-view="settings"]', state="attached", timeout=10000)
        pg.wait_for_timeout(500)

        r["topbar_visible"] = pg.is_visible(".topbar")
        # drawer closed by default on phone → sidebar hidden, nav items not visible
        r["sidebar_hidden_by_default"] = pg.evaluate(
            "() => document.body.classList.contains('sidebar-hidden')"
        ) and not pg.is_visible(".sidebar")

        # no horizontal overflow at 390px
        ov = pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        r["no_horizontal_overflow"] = ov <= 2

        # open the drawer via the topbar toggle
        pg.eval_on_selector("#sidebar-toggle-btn", "el => el.click()")
        pg.wait_for_timeout(400)
        r["toggle_opens_drawer"] = pg.is_visible(".sidebar") and not pg.evaluate(
            "() => document.body.classList.contains('sidebar-hidden')"
        )
        r["backdrop_present_when_open"] = pg.is_visible(".nav-backdrop")
        # drawer overlays (fixed) rather than shoving content — sidebar left edge at 0
        r["drawer_overlays"] = (
            pg.eval_on_selector(".sidebar", "el => Math.round(el.getBoundingClientRect().left)")
            == 0
        )
        # tap target: nav items are comfortably tappable (now that the drawer is open)
        h = pg.eval_on_selector(".nav-item", "el => el.getBoundingClientRect().height")
        r["navitems_tappable_height"] = h >= 38

        # tapping a nav item navigates AND closes the drawer (settings opens its modal)
        pg.eval_on_selector('.nav-item[data-view="settings"]', "el => el.click()")
        pg.wait_for_timeout(600)
        r["navitem_closes_drawer"] = pg.evaluate(
            "() => document.body.classList.contains('sidebar-hidden')"
        )

        # the settings modal fits the viewport — nothing wider than the screen
        widest = pg.evaluate(
            """() => {
                const els = document.querySelectorAll('.s-modal, .modal-card, .model-modal-card, .vault-modal-card');
                let w = 0;
                els.forEach(e => { const r = e.getBoundingClientRect(); if (r.width > w) w = r.width; });
                return w;
            }"""
        )
        r["modal_fits_viewport"] = 0 < widest <= 390

        pg.screenshot(path=str(EVID / "mobile-390.png"))
        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mobile_11b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""2c UI verification — Bases folder-as-database: table/gallery/list + editable cells. :8819."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8819"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{DOCS}/?doc=projects/alpha.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-base-btn", timeout=12000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )

        pg.click("#wiki-base-btn")
        pg.wait_for_selector("#wiki-base .wiki-base-table", timeout=6000)
        r["base_panel_opens"] = pg.is_visible("#wiki-base")
        r["base_table_renders"] = (
            len(pg.query_selector_all("#wiki-base .wiki-base-table tbody tr")) >= 3
        )
        headers = pg.inner_text("#wiki-base .wiki-base-table thead")
        r["base_has_columns"] = "status" in headers and "owner" in headers
        pg.screenshot(path=str(EVID / "base-table.png"))

        # ---- edit a cell ----
        cell = pg.query_selector(
            '#wiki-base .wiki-base-cell[data-path="projects/alpha.md"][data-key="status"]'
        )
        r["cell_present"] = cell is not None
        cell.click()
        pg.wait_for_selector("#wiki-base .wiki-base-input", timeout=3000)
        pg.fill("#wiki-base .wiki-base-input", "paused")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        saved = pg.evaluate(
            "fetch('/api/vault-md/properties?path=projects/alpha.md').then(r=>r.json()).then(j=>j.properties.status)"
        )
        r["cell_edit_persists"] = saved == "paused"

        # ---- view switch ----
        pg.click('#wiki-base .wiki-base-vbtn[data-v="gallery"]')
        pg.wait_for_timeout(300)
        r["view_switch_gallery"] = pg.query_selector("#wiki-base .wiki-base-gallery") is not None
        pg.click('#wiki-base .wiki-base-vbtn[data-v="list"]')
        pg.wait_for_timeout(300)
        r["view_switch_list"] = pg.query_selector("#wiki-base .wiki-base-list") is not None
        pg.screenshot(path=str(EVID / "base-gallery.png"))

        # ---- row opens doc ----
        pg.click('#wiki-base .wiki-base-vbtn[data-v="table"]')
        pg.wait_for_timeout(300)
        pg.click('#wiki-base .wiki-base-open[data-path="projects/beta.md"]')
        pg.wait_for_timeout(600)
        r["row_opens_doc"] = "beta" in pg.inner_text("#wiki-current")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_base_2c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

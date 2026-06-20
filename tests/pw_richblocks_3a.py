"""3a UI verification — rich blocks: toggles, columns, cover+icon, @date mentions. :8822."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8822"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "3a"
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

        pg.goto(f"{DOCS}/?doc=rich.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        # to preview
        for _ in range(3):
            if pg.query_selector("#wiki-preview .md-toggle, #wiki-preview .md-columns"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(350)
        pg.wait_for_selector("#wiki-preview", state="visible", timeout=5000)

        r["toggle_renders"] = pg.query_selector("#wiki-preview details.md-toggle") is not None
        r["toggle_summary"] = "Click me" in (
            pg.inner_text("#wiki-preview .md-toggle summary")
            if pg.query_selector("#wiki-preview .md-toggle summary")
            else ""
        )
        r["columns_render"] = len(pg.query_selector_all("#wiki-preview .md-columns .md-col")) == 2
        r["cover_renders"] = pg.query_selector("#wiki-preview .md-cover") is not None
        r["icon_renders"] = "🚀" in (
            pg.inner_text("#wiki-preview .md-page-icon")
            if pg.query_selector("#wiki-preview .md-page-icon")
            else ""
        )
        dms = pg.query_selector_all("#wiki-preview .md-datemention")
        r["datemention_renders"] = len(dms) >= 2
        pg.screenshot(path=str(EVID / "richblocks.png"))

        # toolbar inserts
        r["toolbar_has_toggle"] = pg.query_selector('#docs-toolbar [data-fmt="toggle"]') is not None
        r["toolbar_has_columns"] = (
            pg.query_selector('#docs-toolbar [data-fmt="columns"]') is not None
        )
        # switch to source, click columns insert → source gains the syntax
        for _ in range(3):
            if pg.is_visible("#wiki-source"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(300)
        pg.click("#wiki-source")
        pg.click('#docs-toolbar [data-fmt="columns"]')
        pg.wait_for_timeout(300)
        src = pg.eval_on_selector("#wiki-source", "el => el.value")
        r["toolbar_insert_columns"] = "::: columns" in src

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_richblocks_3a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

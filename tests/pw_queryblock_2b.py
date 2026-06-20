"""2b UI verification — inline query blocks + saved views. live server :8818."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8818"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def to_preview(pg):
    for _ in range(3):
        if pg.query_selector(
            "#wiki-preview .wiki-queryblock, #wiki-preview .wikilink, #wiki-preview h1"
        ):
            if pg.is_visible("#wiki-preview"):
                return
        pg.click("#wiki-mode-toggle")
        pg.wait_for_timeout(300)


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

        # ---------- inline query block ----------
        pg.goto(f"{DOCS}/?doc=dashboard.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-current", timeout=12000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        # switch to preview so fences render
        for _ in range(3):
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(350)
            if pg.query_selector("#wiki-preview .wiki-queryblock"):
                break
        pg.wait_for_selector("#wiki-preview .wiki-queryblock", timeout=6000)
        r["queryblock_rendered"] = True
        txt = pg.inner_text("#wiki-preview .wiki-queryblock")
        r["queryblock_has_results"] = "p1" in txt and "p2" in txt
        r["queryblock_grouped"] = (
            pg.query_selector("#wiki-preview .wiki-qb-group .wiki-qb-gkey") is not None
        )
        pg.screenshot(path=str(EVID / "queryblock.png"))

        # ---------- query panel + saved views ----------
        # make sure the editor head is available (open any doc), then open query panel
        pg.click("#wiki-query-btn")
        pg.wait_for_selector("#wiki-query .wiki-q-row", timeout=6000)
        r["query_panel_opens"] = pg.is_visible("#wiki-query")
        # fill a filter: field=tag value=project
        pg.fill("#wiki-query .wiki-q-row .wiki-q-field", "tag")
        pg.fill("#wiki-query .wiki-q-row .wiki-q-val", "project")
        # save as a view (prompt dialog)
        pg.click("#wiki-q-save")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "my project view")
        pg.click("#_dy")
        pg.wait_for_selector("#wiki-q-views .wiki-q-view", timeout=5000)
        r["save_view_works"] = "my project view" in pg.inner_text("#wiki-q-views")
        pg.screenshot(path=str(EVID / "savedviews.png"))

        # saved view persists across panel reopen
        pg.click("#wiki-query-btn")  # close
        pg.wait_for_timeout(200)
        pg.click("#wiki-query-btn")  # reopen
        pg.wait_for_selector("#wiki-q-views .wiki-q-view", timeout=5000)
        r["saved_view_persists"] = "my project view" in pg.inner_text("#wiki-q-views")

        # insert as block → editor source gains a ```query fence
        pg.fill("#wiki-query .wiki-q-row .wiki-q-field", "tag")
        pg.fill("#wiki-query .wiki-q-row .wiki-q-val", "project")
        pg.click("#wiki-q-insert")
        pg.wait_for_timeout(500)
        # switch to source mode to read raw text
        for _ in range(3):
            if pg.is_visible("#wiki-source"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(300)
        src = (
            pg.eval_on_selector("#wiki-source", "el => el.value")
            if pg.query_selector("#wiki-source")
            else ""
        )
        r["insert_block_adds_fence"] = "```query" in src

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_queryblock_2b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

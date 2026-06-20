"""3c UI verification — template buttons, Base + row, publish folder→site. :8824."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8824"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "3c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    # keep idempotent — the test creates proj/newrow.md
    Path(r"C:\Users\jxh\AppData\Local\Temp\alles3c_data\vault\proj\newrow.md").unlink(
        missing_ok=True
    )
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

        # ---- template button ----
        pg.goto(f"{DOCS}/?doc=tmpldoc.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        for _ in range(3):
            if pg.query_selector("#wiki-preview .md-tmpl-btn"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(300)
        r["tmpl_button_renders"] = pg.query_selector("#wiki-preview .md-tmpl-btn") is not None
        before = pg.evaluate(
            "fetch('/api/vault-md/file?path=tmpldoc.md').then(r=>r.json()).then(j=>j.content.length)"
        )
        pg.click("#wiki-preview .md-tmpl-btn")
        pg.wait_for_timeout(900)
        after = pg.evaluate(
            "fetch('/api/vault-md/file?path=tmpldoc.md').then(r=>r.json()).then(j=>j.content.length)"
        )
        r["tmpl_button_inserts"] = after > before + 10
        pg.screenshot(path=str(EVID / "tmplbutton.png"))

        # ---- base + row + publish ----
        pg.goto(f"{DOCS}/?doc=proj/a.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-base-btn", timeout=12000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        pg.click("#wiki-base-btn")
        pg.wait_for_selector("#wiki-base .wiki-base-table", timeout=6000)
        rows0 = len(pg.query_selector_all("#wiki-base .wiki-base-table tbody tr"))
        r["base_newrow_button"] = pg.query_selector("#wiki-base-newrow") is not None
        pg.click("#wiki-base-newrow")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "newrow")
        pg.click("#_dy")
        pg.wait_for_timeout(900)
        rows1 = len(pg.query_selector_all("#wiki-base .wiki-base-table tbody tr"))
        r["base_newrow_creates"] = rows1 == rows0 + 1

        r["base_publish_button"] = pg.query_selector("#wiki-base-publish") is not None
        pg.click("#wiki-base-publish")
        pg.wait_for_timeout(900)
        a_tok = pg.evaluate(
            "fetch('/api/vault-md/base?folder=proj').then(()=>fetch('/api/share?kind=doc&ref=proj/a.md')).then(r=>r.json()).then(j=>j.token)"
        )
        r["base_publish_mints"] = bool(a_tok)
        pg.screenshot(path=str(EVID / "basepublish.png"))

        # ---- published site is navigable ----
        if a_tok:
            site = pg.evaluate("(t)=>fetch('/s/'+t).then(r=>r.text())", a_tok)
            r["published_site_navigable"] = "/s/" in site and 'href="/s/' in site
        else:
            r["published_site_navigable"] = False

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_publish_3c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

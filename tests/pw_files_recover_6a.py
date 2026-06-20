"""6a UI verification — starred + storage-quota (trash/versions already shipped). :8849.
Run with ALLES_DATA set so the seed files land in the server's files dir."""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FILES = "http://files.localhost:8849"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "6a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def _reseed():
    base = Path(os.environ.get("ALLES_DATA", "")) / "files"
    base.mkdir(parents=True, exist_ok=True)
    for name, body in [
        ("report.txt", "hello world"),
        ("budget.txt", "budget data"),
        ("notes.md", "# notes"),
    ]:
        (base / name).write_text(body)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    _reseed()
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

        pg.goto(f"{FILES}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".file-row", timeout=15000)
        # reset any stars left over from a previous run (idempotency)
        pg.evaluate(
            "async () => { const d = await fetch('/api/files/starred').then(r=>r.json()); for (const i of d.items) await fetch('/api/files/star?path='+encodeURIComponent(i.path), {method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({starred:false})}); }"
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".file-row", timeout=12000)

        # ---- quota bar ----
        r["quota_bar_shows"] = pg.query_selector("#files-quota .files-quota-bar") is not None
        pg.screenshot(path=str(EVID / "files-recover.png"))

        # ---- star toggle on ----
        pg.eval_on_selector('.file-row[data-path="report.txt"] .file-star', "el => el.click()")
        pg.wait_for_timeout(700)
        r["star_toggle_on"] = (
            pg.query_selector('.file-row[data-path="report.txt"] .file-star.on') is not None
        )

        # ---- persists on reload ----
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".file-row", timeout=12000)
        r["star_persists_reload"] = (
            pg.query_selector('.file-row[data-path="report.txt"] .file-star.on') is not None
        )

        # ---- starred filter lists only starred ----
        pg.click('.files-smart[data-kind="__starred"]')
        pg.wait_for_selector(".file-row", timeout=8000)
        paths = pg.eval_on_selector_all(".file-row", "els => els.map(e => e.dataset.path)")
        r["starred_filter_lists"] = paths == ["report.txt"]

        # ---- star toggle off (back at root) ----
        pg.click("#files-smart-back")
        # wait for the fresh root render where report.txt is still starred, then unstar it
        pg.wait_for_function(
            "() => { const b = document.querySelector('.file-row[data-path=\"report.txt\"] .file-star'); return b && b.classList.contains('on'); }",
            timeout=8000,
        )
        pg.eval_on_selector('.file-row[data-path="report.txt"] .file-star', "el => el.click()")
        pg.wait_for_timeout(800)
        starred_paths = pg.evaluate(
            "() => fetch('/api/files/starred').then(r=>r.json()).then(j=>j.items.map(i=>i.path))"
        )
        r["star_toggle_off"] = "report.txt" not in starred_paths

        # ---- versions button still present (1e) ----
        r["versions_still_work"] = (
            pg.query_selector('.file-row[data-path="report.txt"] [data-act="versions"]') is not None
        )

        # ---- trash still works: delete budget.txt → goes to recently deleted ----
        pg.eval_on_selector(
            '.file-row[data-path="budget.txt"] [data-act="delete"]', "el => el.click()"
        )
        pg.wait_for_selector("#_dy", timeout=4000)
        pg.click("#_dy")
        pg.wait_for_timeout(900)
        pg.click('.files-smart[data-kind="__trash"]')
        pg.wait_for_timeout(800)
        r["trash_still_works"] = "budget.txt" in (pg.text_content("#files-list") or "")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_files_recover_6a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

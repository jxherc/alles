"""1d UI verification — files + photos trash/restore. live isolated server :8814."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FILES = "http://files.localhost:8814"
PHOTOS = "http://photos.localhost:8814"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "1d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def confirm_yes(pg):
    """dismiss the custom confirm() dialog by clicking #_dy (or clearing it)."""
    pg.wait_for_timeout(250)
    try:
        pg.wait_for_selector("#_dy", timeout=2500)
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector(".dialog-overlay", state="detached", timeout=3000)
    except Exception:
        pg.evaluate("document.querySelectorAll('.dialog-overlay').forEach(o => o.remove())")


def main():
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
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

        # ---------- FILES ----------
        pg.goto(f"{FILES}/", wait_until="domcontentloaded")
        pg.wait_for_selector('.file-row[data-path="trashme.txt"]', timeout=15000)
        # delete via the row ✕
        row = pg.query_selector('.file-row[data-path="trashme.txt"]')
        row.query_selector('[data-act="delete"]').click()
        confirm_yes(pg)
        pg.wait_for_timeout(800)
        gone = pg.query_selector('.file-row[data-path="trashme.txt"]') is None
        r["files_deleted_hidden_from_listing"] = gone
        # open recently deleted
        pg.wait_for_selector('.files-smart[data-kind="__trash"]', timeout=8000)
        r["files_trash_button_present"] = True
        pg.click('.files-smart[data-kind="__trash"]')
        pg.wait_for_timeout(700)
        r["files_in_trash_after_delete"] = pg.query_selector(".file-row [data-restore]") is not None
        pg.screenshot(path=str(EVID / "files-trash.png"))
        # restore
        pg.click(".file-row [data-restore]")
        pg.wait_for_timeout(800)
        pg.goto(f"{FILES}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        r["files_restored_back"] = (
            pg.query_selector('.file-row[data-path="trashme.txt"]') is not None
        )
        pg.click('.files-smart[data-kind="__trash"]')
        pg.wait_for_timeout(700)
        r["files_gone_from_trash_after_restore"] = (
            pg.query_selector(".file-row [data-restore]") is None
        )

        # ---------- PHOTOS ----------
        pg.goto(f"{PHOTOS}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".photos-cell", timeout=15000)
        r["photos_trash_button_present"] = pg.query_selector("#photos-trash-btn") is not None
        pg.evaluate("document.querySelectorAll('.dialog-overlay').forEach(o => o.remove())")
        pg.click(".photos-cell")  # open lightbox
        pg.wait_for_selector("#photos-del-btn", state="visible", timeout=8000)
        pg.click("#photos-del-btn")
        confirm_yes(pg)
        pg.wait_for_timeout(900)
        r["photos_deleted_hidden"] = pg.query_selector(".photos-cell") is None
        pg.click("#photos-trash-btn")
        pg.wait_for_timeout(700)
        r["photos_in_trash"] = pg.query_selector(".photos-restore") is not None
        pg.screenshot(path=str(EVID / "photos-trash.png"))
        pg.click(".photos-restore")
        pg.wait_for_timeout(900)
        pg.goto(f"{PHOTOS}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        r["photos_restored_back"] = pg.query_selector(".photos-cell") is not None

        r["zero_console_errors"] = len(errs) == 0
        ctx.close()
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_trash_1d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

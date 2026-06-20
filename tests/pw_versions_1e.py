"""1e UI verification — files version history popover + restore. live server :8815."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FILES = "http://files.localhost:8815"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "1e"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

UPLOAD = """
async (content) => {
  const fd = new FormData();
  fd.append('path', '');
  fd.append('file', new Blob([content], {type:'text/plain'}), 'ver.txt');
  const r = await fetch('/api/files/upload', {method:'POST', body: fd});
  return r.status;
}
"""


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

        pg.goto(f"{FILES}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        # seed: upload ver.txt twice (v1 then v2 → one prior version = v1)
        pg.evaluate(UPLOAD, "v1-content")
        pg.evaluate(UPLOAD, "v2-content")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector('.file-row[data-path="ver.txt"]', timeout=15000)

        row = pg.query_selector('.file-row[data-path="ver.txt"]')
        r["versions_button_present"] = row.query_selector('[data-act="versions"]') is not None
        row.query_selector('[data-act="versions"]').click()
        pg.wait_for_selector('.file-row[data-path="ver.txt"] .file-verpop', timeout=5000)
        r["popover_opens"] = True
        r["popover_lists_version"] = pg.query_selector(".file-verpop [data-restore]") is not None
        pg.screenshot(path=str(EVID / "versions-popover.png"))

        # current content is v2 before restore
        before = pg.evaluate(
            "fetch('/api/files/read?path=ver.txt').then(r=>r.json()).then(j=>j.content)"
        )
        r["current_is_latest_before_restore"] = before == "v2-content"

        pg.click(".file-verpop [data-restore]")
        pg.wait_for_timeout(1000)
        after = pg.evaluate(
            "fetch('/api/files/read?path=ver.txt').then(r=>r.json()).then(j=>j.content)"
        )
        r["restore_reverts_content"] = after == "v1-content"
        r["popover_closed_after_restore"] = pg.query_selector(".file-verpop") is None

        # restore snapshotted the pre-restore v2 → now there are 2 versions
        vs = pg.evaluate("fetch('/api/files/versions?path=ver.txt').then(r=>r.json())")
        r["restore_is_undoable"] = len(vs) >= 2

        r["zero_console_errors"] = len(errs) == 0
        ctx.close()
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_versions_1e.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

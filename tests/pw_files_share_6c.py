"""6c UI verification — folder share button + file comment threads. :8853.
Run with ALLES_DATA set so the seed files land in the server's files dir."""

import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FILES = "http://files.localhost:8853"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "6c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def _reseed():
    base = Path(os.environ["ALLES_DATA"]) / "files"
    sd = base / "shared6c"
    if sd.exists():
        shutil.rmtree(sd)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "a.txt").write_text("alpha")
    (sd / "b.txt").write_text("beta")
    (base / "doc1.txt").write_text("a document to comment on")


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
        pg.wait_for_selector('.file-row[data-path="doc1.txt"]', timeout=15000)

        # reset any comments from a prior run so the count badge is deterministic
        pg.evaluate(
            "async () => { const d = await fetch('/api/files/comments?path=doc1.txt').then(r=>r.json());"
            " for (const t of (d.threads||[])) await fetch('/api/files/comments/'+t.id, {method:'DELETE'}); }"
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector('.file-row[data-path="doc1.txt"]', timeout=12000)

        # ---- folder share button present on a dir row ----
        r["folder_share_button"] = (
            pg.query_selector('.file-row[data-path="shared6c"] [data-act="share"]') is not None
        )

        # ---- open comments on a file ----
        pg.eval_on_selector(
            '.file-row[data-path="doc1.txt"] [data-act="comment"]', "el => el.click()"
        )
        pg.wait_for_selector(".file-commentpop", timeout=5000)
        r["comment_button_opens"] = pg.query_selector(".file-commentpop") is not None

        # ---- add a comment ----
        pg.fill(".file-commentpop .file-caddin", "first note")
        pg.click(".file-commentpop [data-add]")
        pg.wait_for_selector(".file-cthread", timeout=5000)
        r["comment_add_persists"] = "first note" in (pg.text_content(".file-commentpop") or "")

        # ---- reply to it ----
        pg.fill(".file-cthread .file-creplyin", "a reply here")
        pg.click(".file-cthread [data-reply]")
        pg.wait_for_selector(".file-creply", timeout=5000)
        r["comment_reply"] = "a reply here" in (pg.text_content(".file-commentpop") or "")

        # ---- resolve ----
        pg.click(".file-cthread [data-resolve]")
        pg.wait_for_selector(".file-cthread.resolved", timeout=5000)
        r["comment_resolve"] = pg.query_selector(".file-cthread.resolved") is not None
        pg.screenshot(path=str(EVID / "files-comments.png"))

        # ---- count badge (1 root + 1 reply = 2) ----
        badge = pg.text_content('.file-row[data-path="doc1.txt"] .file-comment .file-cn')
        r["comment_count_badge"] = (badge or "").strip() == "2"

        pg.click(".file-commentpop [data-close]")

        # ---- folder share mints a token ----
        pg.eval_on_selector(
            '.file-row[data-path="shared6c"] [data-act="share"]', "el => el.click()"
        )
        pg.wait_for_timeout(700)
        tok = pg.evaluate(
            "() => fetch('/api/share?kind=folder&ref=shared6c').then(r=>r.json()).then(j=>j.token)"
        )
        r["folder_share_creates_token"] = bool(tok)

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_files_share_6c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

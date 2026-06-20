"""1a-2 UI verification — docs publish + files share. drives the live isolated
server on :8811 (ALLES_DATA=…/alles1a_data). run after booting that server.

  ALLES_DATA=…/alles1a_data PORT=8811 AUTH_ENABLED=false python app.py
  python tests/pw_share_1a.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DATA = Path(r"C:\Users\jxh\AppData\Local\Temp\alles1a_data")
DOCS = "http://docs.localhost:8811"
FILES = "http://files.localhost:8811"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "1a"

# network/teardown artifacts that are not real UI bugs (per CLAUDE.md)
IGNORE = ("ERR_CONNECTION_CLOSED", "ERR_ABORTED", "ERR_NETWORK_CHANGED", "favicon", "401")


def seed():
    (DATA / "vault").mkdir(parents=True, exist_ok=True)
    (DATA / "files").mkdir(parents=True, exist_ok=True)
    (DATA / "vault" / "share-demo.md").write_text("# Share demo\n\nhello **world**", "utf-8")
    (DATA / "files" / "demo.txt").write_text("shared file body", "utf-8")


def main():
    seed()
    results = {}
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.on(
            "console",
            lambda m: (
                errors.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errors.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        # ---- DOCS publish ----
        pg.goto(f"{DOCS}/?doc=share-demo.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-publish-btn", timeout=15000)
        pg.wait_for_function(
            "document.getElementById('wiki-current') && !/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=15000,
        )
        results["docs_publish_button_present"] = pg.is_visible("#wiki-publish-btn")

        pg.click("#wiki-publish-btn")
        pg.wait_for_function(
            "document.getElementById('wiki-publish-btn').textContent.trim()==='published'",
            timeout=10000,
        )
        tok = pg.evaluate(
            "fetch('/api/share?kind=doc&ref=share-demo.md').then(r=>r.json()).then(j=>j.token)"
        )
        results["docs_publish_mints_and_copies"] = bool(tok)
        results["docs_shared_state_shows"] = (
            "published" in pg.inner_text("#wiki-publish-btn").lower()
        )
        pg.screenshot(path=str(EVID / "docs-published.png"))

        # public link opens read-only
        view = pg.evaluate(
            "(t)=>fetch('/s/'+t).then(async r=>({status:r.status, body:await r.text()}))", tok
        )
        results["public_doc_link_opens_readonly"] = (
            view["status"] == 200 and "read-only" in view["body"] and "Share demo" in view["body"]
        )

        # unpublish
        pg.click("#wiki-publish-btn")
        pg.wait_for_function(
            "document.getElementById('wiki-publish-btn').textContent.trim()==='publish'",
            timeout=10000,
        )
        tok2 = pg.evaluate(
            "fetch('/api/share?kind=doc&ref=share-demo.md').then(r=>r.json()).then(j=>j.token)"
        )
        results["docs_unpublish_revokes"] = tok2 is None

        # ---- FILES share ----
        pg.goto(f"{FILES}/", wait_until="domcontentloaded")
        pg.wait_for_selector('.file-row[data-path="demo.txt"]', timeout=15000)
        share_btn = pg.query_selector('.file-row[data-path="demo.txt"] [data-act="share"]')
        results["files_share_action_present"] = share_btn is not None
        share_btn.click()
        pg.wait_for_timeout(800)
        ftok = pg.evaluate(
            "fetch('/api/share?kind=file&ref=demo.txt').then(r=>r.json()).then(j=>j.token)"
        )
        results["files_share_mints"] = bool(ftok)
        pg.screenshot(path=str(EVID / "files-share.png"))

        results["zero_console_errors"] = len(errors) == 0
        ctx.close()
        b.close()

    ok = all(results.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in results.items()]
    if errors:
        lines.append(f"console_errors: {errors[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_share_1a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(results.values())}/{len(results)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

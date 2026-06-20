"""3b UI verification — live embeds (iframe) + synced blocks (mirror). :8823."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8823"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "3b"
IGNORE = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "favicon",
    "401",
    "Load failed",
    "frame",
    "X-Frame",
    "sandbox",
)


def to_preview(pg):
    for _ in range(3):
        if pg.query_selector("#wiki-preview .md-syncblock, #wiki-preview .md-live-embed"):
            return
        pg.click("#wiki-mode-toggle")
        pg.wait_for_timeout(350)


def main():
    # reset the source block (the test edits it; keep it idempotent)
    Path(r"C:\Users\jxh\AppData\Local\Temp\alles3b_data\vault\src.md").write_text(
        "shared idea here ^idea\n\nmore text in source\n", encoding="utf-8"
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

        pg.goto(f"{DOCS}/?doc=embed.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        to_preview(pg)
        pg.wait_for_timeout(600)

        r["live_embed_iframe"] = (
            pg.query_selector("#wiki-preview .md-live-embed iframe") is not None
        )
        ifr_src = (
            pg.eval_on_selector("#wiki-preview .md-live-embed iframe", "el => el.src")
            if r["live_embed_iframe"]
            else ""
        )
        r["iframe_src_youtube"] = "youtube.com/embed/" in ifr_src
        r["syncblock_renders"] = pg.query_selector("#wiki-preview .md-syncblock") is not None
        sync_txt = pg.inner_text("#wiki-preview .md-syncblock") if r["syncblock_renders"] else ""
        r["syncblock_content"] = "shared idea here" in sync_txt
        r["syncblock_src_label"] = "synced from" in sync_txt
        pg.screenshot(path=str(EVID / "embeds.png"))

        # edit the source block → the synced reference reflects it on re-render
        pg.evaluate(
            """() => fetch('/api/vault-md/file', {method:'PUT', headers:{'content-type':'application/json'}, body: JSON.stringify({path:'src.md', content:'UPDATED idea text ^idea\\n\\nmore'})})"""
        )
        pg.wait_for_timeout(500)
        pg.goto(f"{DOCS}/?doc=embed.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=10000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        to_preview(pg)
        pg.wait_for_timeout(600)
        r["sync_reflects_edit"] = "UPDATED idea text" in (
            pg.inner_text("#wiki-preview .md-syncblock")
            if pg.query_selector("#wiki-preview .md-syncblock")
            else ""
        )

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_embeds_3b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""3e UI verification — inline comments: panel, select-to-comment, anchor highlight,
reply, resolve, delete. :8827."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8827"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "3e"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")
DOC = "notes/comment-doc.md"


def to_preview(pg):
    for _ in range(4):
        if pg.eval_on_selector("#wiki-preview", "el => getComputedStyle(el).display !== 'none'"):
            return
        pg.click("#wiki-mode-toggle")
        pg.wait_for_timeout(400)


def select_phrase(pg, phrase):
    return pg.evaluate(
        """(phrase) => {
            const pv = document.getElementById('wiki-preview');
            const walker = document.createTreeWalker(pv, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const idx = node.nodeValue.indexOf(phrase);
                if (idx !== -1) {
                    const range = document.createRange();
                    range.setStart(node, idx); range.setEnd(node, idx + phrase.length);
                    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
                    pv.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                    return true;
                }
            }
            return false;
        }""",
        phrase,
    )


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

        # seed the doc + clear any leftover comments (idempotent)
        pg.goto(f"{DOCS}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        pg.evaluate(
            "(d)=>fetch('/api/vault-md/file',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({path:d,content:'# Notes\\n\\nthe quick brown fox jumps over the lazy dog'})})",
            DOC,
        )
        pg.wait_for_timeout(400)
        pg.evaluate(
            """async (d) => {
                const r = await fetch('/api/vault-md/comments?path='+encodeURIComponent(d)).then(x=>x.json());
                for (const t of (r.threads||[])) await fetch('/api/vault-md/comments/'+t.id,{method:'DELETE'});
            }""",
            DOC,
        )

        pg.goto(f"{DOCS}/?doc={DOC}", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-comments-btn", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )

        # ---- panel opens ----
        pg.click("#wiki-comments-btn")
        pg.wait_for_selector("#wiki-comments", state="visible", timeout=5000)
        r["comments_panel_opens"] = pg.is_visible("#wiki-comments")

        # ---- select text → fab appears ----
        to_preview(pg)
        pg.wait_for_timeout(400)
        select_phrase(pg, "quick brown fox")
        pg.wait_for_timeout(300)
        r["select_text_shows_comment_btn"] = pg.is_visible("#wiki-comment-fab")

        # ---- add comment ----
        pg.click("#wiki-comment-fab")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "needs a citation")
        pg.click("#_dy")
        pg.wait_for_selector("#wiki-comments .wiki-cmt-thread", timeout=6000)
        threads = pg.query_selector_all("#wiki-comments .wiki-cmt-thread")
        body = pg.text_content("#wiki-comments") or ""
        r["add_comment_creates_thread"] = len(threads) == 1 and "needs a citation" in body
        pg.screenshot(path=str(EVID / "comments-panel.png"))

        # ---- anchor highlighted in preview ----
        for _ in range(3):
            if pg.query_selector("#wiki-preview mark.wiki-cmark"):
                break
            pg.wait_for_timeout(400)
        r["anchor_highlighted_in_preview"] = (
            pg.query_selector("#wiki-preview mark.wiki-cmark") is not None
        )

        # ---- reply ----
        pg.fill("#wiki-comments .wiki-cmt-reply-input", "agreed, sourcing it")
        pg.press("#wiki-comments .wiki-cmt-reply-input", "Enter")
        pg.wait_for_selector("#wiki-comments .wiki-cmt-reply", timeout=5000)
        r["reply_adds_to_thread"] = "agreed, sourcing it" in (
            pg.text_content("#wiki-comments") or ""
        )

        # ---- resolve ----
        pg.click("#wiki-comments .wiki-cmt-resolve")
        pg.wait_for_timeout(700)
        r["resolve_marks_resolved"] = (
            pg.query_selector("#wiki-comments .wiki-cmt-thread.resolved") is not None
        )

        # ---- delete ----
        pg.click("#wiki-comments .wiki-cmt-del")
        pg.wait_for_selector("#_dy", timeout=4000)
        pg.click("#_dy")
        pg.wait_for_timeout(700)
        r["delete_removes_thread"] = (
            len(pg.query_selector_all("#wiki-comments .wiki-cmt-thread")) == 0
        )

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_comments_3e.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

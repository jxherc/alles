"""2a UI verification — folding, hover preview, bookmarks, hierarchical tag tree. :8817."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8817"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2a"
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

        # ---------- FOLDING (live editor) ----------
        pg.goto(f"{DOCS}/?doc=folddemo.md", wait_until="domcontentloaded")
        pg.wait_for_selector(".cm-editor", timeout=15000)
        pg.wait_for_selector(".cm-foldGutter", timeout=8000)
        r["fold_gutter_present"] = True
        # click the first fold marker in the gutter
        marker = pg.evaluate("""() => {
            const els = [...document.querySelectorAll('.cm-foldGutter .cm-gutterElement')];
            const m = els.find(e => (e.textContent||'').trim().length);
            if (m) { m.click(); return true; }
            return false;
        }""")
        pg.wait_for_timeout(500)
        r["fold_marker_clickable"] = marker
        r["fold_collapses_section"] = pg.query_selector(".cm-foldPlaceholder") is not None
        pg.screenshot(path=str(EVID / "folding.png"))

        # ---------- HOVER PREVIEW (preview mode) ----------
        pg.goto(f"{DOCS}/?doc=linksource.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-current", timeout=10000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        # cycle mode to preview (live -> source -> preview)
        for _ in range(3):
            if pg.query_selector("#wiki-preview .wikilink"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(300)
        link = pg.query_selector("#wiki-preview .wikilink")
        r["preview_wikilink_present"] = link is not None
        if link:
            link.hover()
            try:
                pg.wait_for_selector("#wiki-hoverpop", timeout=4000)
                r["hover_preview_appears"] = True
                r["hover_preview_has_excerpt"] = "target excerpt" in pg.inner_text("#wiki-hoverpop")
            except Exception:
                r["hover_preview_appears"] = False
                r["hover_preview_has_excerpt"] = False
        pg.screenshot(path=str(EVID / "hover.png"))

        # ---------- BOOKMARKS ----------
        pg.goto(f"{DOCS}/?doc=folddemo.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-bookmark-btn", timeout=10000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        pg.click("#wiki-bookmark-btn")
        pg.wait_for_function(
            "document.getElementById('wiki-bookmark-btn').textContent.trim()==='★'", timeout=5000
        )
        r["bookmark_toggles_on"] = True
        pg.click("#wiki-home-btn")
        pg.wait_for_timeout(800)
        r["bookmark_shows_on_home"] = (
            pg.query_selector('.docs-bm[data-path="folddemo.md"]') is not None
        )
        if r["bookmark_shows_on_home"]:
            pg.click('.docs-bm[data-path="folddemo.md"]')
            pg.wait_for_timeout(600)
            r["bookmark_home_opens_doc"] = "folddemo" in pg.inner_text("#wiki-current")
        else:
            r["bookmark_home_opens_doc"] = False
        pg.screenshot(path=str(EVID / "bookmarks.png"))

        # ---------- TAG TREE ----------
        # open the tree sidebar
        if pg.query_selector("#wiki-view.tree-hidden"):
            pg.click("#wiki-tree-toggle")
            pg.wait_for_timeout(400)
        pg.wait_for_selector("#wiki-tags .wiki-tag-node", timeout=8000)
        # find the 'project' parent node with nested children
        nested = pg.evaluate("""() => {
            const nodes = [...document.querySelectorAll('#wiki-tags .wiki-tag-node')];
            const parent = nodes.find(n => /#project\\b/.test(n.querySelector('.wiki-tag')?.textContent||'') && n.querySelector('.wiki-tag-children'));
            return !!parent;
        }""")
        r["tag_tree_nested"] = nested
        toggled = pg.evaluate("""() => {
            const nodes = [...document.querySelectorAll('#wiki-tags .wiki-tag-node')];
            const parent = nodes.find(n => n.querySelector('.wiki-tag-children') && n.querySelector('.wiki-tag-toggle'));
            if (!parent) return false;
            parent.querySelector('.wiki-tag-toggle').click();
            return parent.classList.contains('collapsed');
        }""")
        r["tag_tree_toggle_collapses"] = toggled
        pg.screenshot(path=str(EVID / "tagtree.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_docs_powerups_2a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""docs + notes UI depth smoke. :8895."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8895"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "docs"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def _visible(pg, sel):
    return pg.eval_on_selector(
        sel,
        "el => !!el && el.offsetParent !== null && el.getBoundingClientRect().height > 0",
    )


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
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

        pg.goto(f"{DOCS}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.evaluate(
            """async () => {
                const post = (url, body) => fetch(url, {
                    method:'POST',
                    headers:{'content-type':'application/json'},
                    body:JSON.stringify(body),
                });
                for (const f of ['index.md', 'project.md', 'nested/daily.md', 'browser created.md']) {
                    await fetch('/api/vault-md/file?path=' + encodeURIComponent(f), {method:'DELETE'});
                }
                const notes = await fetch('/api/notes').then(r => r.json()).catch(() => []);
                for (const n of notes) await fetch('/api/notes/' + encodeURIComponent(n.id), {method:'DELETE'});
                await post('/api/vault-md/file', {
                    path:'index',
                    content:'# Index\\n\\n#alpha\\nSee [[project]] and [[missing target]].\\n',
                });
                await post('/api/vault-md/file', {
                    path:'project',
                    content:'# Project\\n\\n#alpha/child\\nProject body has orbit banana and a task.\\n- [ ] ship docs\\n',
                });
                await post('/api/vault-md/file', {
                    path:'nested/daily',
                    content:'# Daily\\n\\n#daily\\nBack to [[project]].\\n',
                });
                await post('/api/notes', {
                    title:'browser note',
                    content:'remember blue comet',
                    tags:['audit'],
                    items:[{text:'first item', done:false}],
                });
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector('#wiki-tree .wiki-file[data-file="index.md"]', timeout=15000)

        r["docs_tree_lists_files"] = (
            pg.query_selector('#wiki-tree .wiki-file[data-file="index.md"]') is not None
            and pg.query_selector('#wiki-tree .wiki-file[data-file="project.md"]') is not None
            and pg.query_selector('#wiki-tree .wiki-file[data-file="nested/daily.md"]') is not None
        )

        pg.click('#wiki-tree .wiki-file[data-file="index.md"]')
        pg.wait_for_function("document.getElementById('wiki-current')?.textContent === 'index'")
        prev = pg.text_content("#wiki-preview") or ""
        r["docs_render_markdown_and_wikilink"] = (
            "Index" in prev
            and pg.query_selector('#wiki-preview a[href="#wiki=project"]') is not None
        )

        pg.click('#wiki-preview a[href="#wiki=project"]')
        pg.wait_for_function("document.getElementById('wiki-current')?.textContent === 'project'")
        pg.wait_for_selector('#wiki-backlinks .wiki-bl[data-file="index.md"]', state="attached", timeout=8000)
        r["wikilink_opens_doc_and_backlinks_render"] = (
            "orbit banana" in (pg.text_content("#wiki-preview") or "")
            and "index" in (pg.text_content("#wiki-backlinks") or "").lower()
        )

        pg.fill("#wiki-search", "orbit banana")
        pg.wait_for_function("document.querySelector('#wiki-tree')?.textContent.includes('orbit banana')")
        r["docs_search_filters_with_context"] = (
            "project" in (pg.text_content("#wiki-tree") or "").lower()
            and "orbit banana" in (pg.text_content("#wiki-tree") or "")
        )
        pg.fill("#wiki-search", "")
        pg.wait_for_timeout(300)
        pg.wait_for_selector('#wiki-tree .wiki-file[data-file="index.md"]', timeout=8000)

        pg.wait_for_selector('#wiki-tags .wiki-tag[data-tag="alpha"]', timeout=8000)
        pg.click('#wiki-tags .wiki-tag[data-tag="alpha"]')
        pg.wait_for_selector("#wiki-tag-clear", state="attached", timeout=8000)
        r["docs_tag_filter_and_clear"] = (
            "index" in (pg.text_content("#wiki-tree") or "").lower()
            and pg.query_selector("#wiki-tag-clear") is not None
        )
        pg.click("#wiki-tag-clear")
        pg.wait_for_selector('#wiki-tree .wiki-file[data-file="project.md"]', timeout=8000)

        pg.click("#wiki-ask-btn")
        pg.fill("#wiki-ask-input", "orbit banana")
        pg.click("#wiki-ask-go")
        pg.wait_for_function(
            "document.querySelector('#wiki-ask-results')?.textContent.toLowerCase().includes('project')"
        )
        r["docs_ask_returns_source"] = "project" in (
            pg.text_content("#wiki-ask-results") or ""
        ).lower()

        pg.once("dialog", lambda d: d.accept("browser created"))
        pg.click("#wiki-new-btn")
        pg.wait_for_function(
            "document.getElementById('wiki-current')?.textContent === 'browser created'"
        )
        r["docs_new_doc_opens"] = (
            pg.query_selector('#wiki-tree .wiki-file[data-file="browser created.md"]') is not None
        )

        pg.click("#wiki-tree-toggle")
        r["docs_tree_toggle_hides_panel"] = pg.eval_on_selector(
            ".wiki-tree-panel", "el => el.classList.contains('hidden')"
        )
        pg.click("#wiki-tree-toggle")

        pg.click('.docs-sec-btn[data-section="notes"]')
        pg.wait_for_function(
            "document.getElementById('wiki-notes')?.offsetParent !== null"
        )
        pg.wait_for_function("document.querySelector('#notes-list')?.textContent.includes('browser note')")
        r["notes_tab_lists_seeded_note"] = (
            _visible(pg, "#wiki-notes")
            and "blue comet" in (pg.text_content("#notes-list") or "")
        )

        pg.wait_for_selector('.note-tag-chip[data-tag="audit"]', timeout=8000)
        pg.click('.note-tag-chip[data-tag="audit"]')
        pg.wait_for_function("document.querySelector('#notes-list')?.textContent.includes('browser note')")
        pg.fill("#note-search", "blue comet")
        pg.wait_for_timeout(350)
        pg.wait_for_function("document.querySelector('#notes-list')?.textContent.includes('browser note')")
        r["notes_search_and_tag_filter"] = "browser note" in (
            pg.text_content("#notes-list") or ""
        )
        pg.fill("#note-search", "")
        pg.wait_for_timeout(350)
        pg.click('.note-tag-chip[data-tag=""]')
        pg.wait_for_timeout(350)
        pg.wait_for_function("document.querySelector('#notes-list')?.textContent.includes('browser note')")

        pg.click("#note-new-btn")
        pg.wait_for_selector("#note-edit-title", timeout=8000)
        pg.fill("#note-edit-title", "browser scratch")
        pg.fill("#note-edit-body", "plain body for the note")
        pg.fill("#note-edit-tags", "audit, scratch")
        pg.click("#note-add-item")
        pg.fill("#note-checklist .note-cl-row:last-child .note-cl-text", "save this")
        pg.check("#note-checklist .note-cl-row:last-child .note-cl-done")
        pg.click("#note-save-btn")
        pg.wait_for_timeout(400)
        pg.click("#note-back-btn")
        pg.wait_for_function("document.querySelector('#notes-list')?.textContent.includes('browser scratch')")
        notes_txt = pg.text_content("#notes-list") or ""
        r["notes_new_edit_checklist_roundtrip"] = (
            "browser scratch" in notes_txt
            and "plain body" in notes_txt
            and "scratch" in notes_txt
            and "1/1" in notes_txt
        )

        pg.screenshot(path=str(EVID / "docs-depth.png"))
        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_docs_depth.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

# docs — follow-up #2 (2026-06-18): selection escapes page + sidebar on home

User re-reported (with screenshots) that the first docs pass didn't actually fix things.

## 1. Text selection still spanned the full screen
Diagnosed at 1920px: `.cm-content` WAS capped at 820px, but CodeMirror draws its selection in a
`.cm-selectionBackground` layer that lives in `.cm-scroller` (full editor width = 1919px), not clipped to
`.cm-content`. So selection right-edge reached ~1370–1800px and "copying grabbed the sides". The earlier
`.cm-scroller{justify-content:center}` + `.cm-content{max-width}` was fragile (content centered, but the
selection layer didn't).
**Fix:** cap the whole `.cm-editor` to `max-width:820px` and center it via `.wiki-live{justify-content:center}`,
so scroller + content + selection layer are all inside the 820px page. Source/preview get the same centered
cap. Measured after: editor 549→1370 at 1920px, selection max-right = 1370 (= page edge), min-left = 550.

## 2. Docs home still had the tree sidebar (redundant with the gallery)
The home showed `.wiki-tree-panel` (today/week/month/+doc/search/file-list) on the left AND the new card
gallery in the main column — the user's "why do you need a sidebar in the home page".
**Fix:** `#wiki-view.no-note` hides `.wiki-tree-panel` and `.docs-editor-head`. The home is now the clean
gallery only (title + new doc / today / guide + search + centered card grid). Opening a doc (click a card)
restores the editor head + `☰` tree toggle, so the full rail is one click away when actually editing.

CSS-only (`static/style.css`). Verified `pw_docs_fix2.py` 10/10 @1920px; full docs suite still green
(`pw_docs_ui1` 9/9, `pw_docs_page1` 8/8, `pw_docs_home1` 9/9 — their home-open steps updated to click a
gallery card since the tree toggle is no longer on the home). Screenshots: `fix2-home.png`, `fix2-selection.png`.

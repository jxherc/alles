# Phase 1 — docs (the `wiki` view: `vaultmd.js` + `routes/vault_md.py` + `services/vault_md.py`)

## Audit (2026-06-18)

Real docs app = the **wiki** view, powered by `static/js/vaultmd.js` (1179 lines) over the file-based
markdown vault in `services/vault_md.py` / `routes/vault_md.py`. (`documents.js` is a *separate* small
CRUD store, not the docs editor.)

Verified working (DO NOT rebuild): 3 modes (live CM6 / source / preview), full format toolbar
(bold/italic/strike/highlight/code, h1–h3, lists/check/quote, link/image/wiki, hr, table snippet,
codeblock, callout, math, mermaid, color picker), `[[` wikilink autocomplete, backlinks, **quick
switcher (Ctrl/Cmd+O)**, CM6 find (Ctrl+F), daily notes, global graph, outline, tags + filter, sidebar
search + grep, templates, import (md/txt/docx/html/pdf), export (docx/pdf), revisions + diff + restore,
AI edit (stream), extract-todos, vault-wide task rollup, image paste/drop → embed, folders + drag-move +
pin + sort + collapse. UI loads with **0 console errors** (Playwright, docs.localhost).

Frontmatter is **display-only** (`renderFrontmatter` just renders k/v in preview) — no editor.

## Confirmed gaps → tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **docs-1 Properties (frontmatter) editor.** Backend: `vault_md.parse_frontmatter`/`set_frontmatter`
  (+ typed values) and `GET/PUT /api/vault-md/properties`. Frontend: editable properties panel in the
  doc header. *Why: editing note metadata is core Obsidian Properties; today it's read-only.*
- **docs-2 Periodic notes (weekly + monthly).** Backend: `vault_md.periodic_path(kind,date)` +
  `open_or_create_periodic` + `POST /api/vault-md/periodic`. Frontend: week/month buttons by "today".
  *Why: daily notes exist; weekly/monthly reviews are the standard companion.*
- **docs-3 Note query (dataview-lite).** Backend: `vault_md.query_notes(filters,sort,limit)` over
  frontmatter props + tags + `POST /api/vault-md/query`. Frontend: query panel → results table.
  *Why: finding notes by property/tag is a top power-feature; nothing like it exists.*
- **docs-4 Kanban board.** Backend: `vault_md.parse_board`/`board_move_card`/`board_add_card`
  (markdown `## Column` + `- [ ]` cards) + endpoints. Frontend: board view toggle, drag between
  columns, add card → writes back to the file. *Why: kanban over a markdown doc is heavily used; none.*
- **docs-5 Local graph + filters.** Backend: `vault_md.local_graph(name,depth)` + tag/folder filter on
  `graph()` + `GET /api/vault-md/local-graph`. Frontend: "local" toggle + filter input in graph overlay.
  *Why: global graph exists, but local (around current note) + filters are the daily-use variants.*
- **docs-6 Slash `/` insert menu.** Backend: `vault_md.slash_commands()` registry + per-command snippet
  builder + filter helper (the testable core). Frontend: typing `/` opens a filterable insert menu.
  *Why: `/` insert is the biggest editor-speed feature users expect; only `[[` autocomplete exists.*

## Evaluated but out of scope (avoid half-features / low ROI for single-user notes)

Full Canvas (large, low daily ROI); split panes/tabs (large frontend, marginal single-user); a separate
command-*action* palette (quick switcher already covers note-open, slash menu covers insertion); floating
selection toolbar / focus-zen mode / auto-hide sidebar / heading-size dropdown / smart-paste URL→link
(nice-to-have polish; toolbar + image-paste already cover the core). Revisit in phase 15 if they prove to
matter.

---

# docs — UI/UX polish (2026-06-18)

Re-audit evidence: `docs/evidence/docs/` (findings.md + 4 screenshots + audit.json). Editor flows all
work, zero console errors. Two defects: no per-doc URL (refresh drops to home — user-reported); and in the
default tree-hidden state the action buttons strand at the far-right edge with a 482px dead gap.

## docs-ui-1 — per-doc URL routing + editor-head balance

**Change:**
- `static/js/vaultmd.js`: `openFile()` → `history.replaceState` the path into `?doc=<path>`;
  `_resetEditor()` clears `?doc`; `initVault()` reads `?doc=` after `loadTree()` and opens it (deep-link +
  refresh restore the open doc).
- `static/index.html`: drop the `margin-left:auto` inline on `#wiki-stats`.
- `static/style.css`: `.docs-editor-head { justify-content: flex-start }` so name + stats + buttons form
  one left-aligned cluster (no far-right stranding / dead gap), buttons still tightly grouped.

**Verify (Playwright `pw_docs_ui1.py`, ≥8 assertions, RED→GREEN, screenshot, 0 console err):**
1. `head_no_dead_gap` — first action button within 150px of the doc-name right edge (was 482).
2. `head_left_aligned` — doc-name, stats, first button all in the left portion (x < viewport/2).
3. `head_buttons_grouped` — inter-button gaps stay small (<16px) — still one cluster.
4. `open_sets_doc_url` — opening a doc puts `?doc=` in the URL.
5. `doc_url_matches_path` — the `?doc=` value equals the opened doc path.
6. `reload_restores_doc` — after reload, `#wiki-current` == opened doc, empty state hidden.
7. `deep_link_opens` — visiting `?doc=<path>` directly opens that doc.
8. `switch_updates_url` — opening a second doc updates `?doc=` to the new path.
9. `zero_console_errors` — no console/page errors; screenshot saved.

---

# docs — Google-Docs-style page + home (2026-06-18, user follow-up)

User follow-up: text selection in the editor looks awkward (full-bleed grey across the ultra-wide
editor), and the docs home should look like Google Docs (a gallery of docs; click opens the doc).
Evidence: `docs/evidence/docs/before-home.png`, `before-selection.png`, `page1-selection.png`.

## docs-page-1 — center the editor as a page + fix selection
Live CM editor spanned the full 1279px width, so text + selection were full-bleed. `static/style.css`:
center `.cm-content` (max-width 820px via `.cm-scroller{justify-content:center}` + page padding) and tint
the selection (`.cm-selectionBackground` → translucent accent) so it reads like a Google-Docs page.
**Verify (`pw_docs_page1.py`, 8 assertions, screenshot, 0 console err):** content_constrained (<860),
content_centered_left/right, page_has_padding, editor_editable, selection_within_page (not full-bleed),
selection_tinted (translucent accent), zero_console_errors.

## docs-home-1 — Google-Docs-style docs home gallery
Replace the small centered empty-state card (8 pill links) with a real home: a header (+ new doc / today /
guide) + a search box + a responsive grid of doc **cards** (title · folder · modified date), all docs,
click → open; plus an "all docs" affordance in the editor head to return home. (see below verify)

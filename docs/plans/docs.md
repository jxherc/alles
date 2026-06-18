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

# 3d audit — Workspace AI + DB extras

Booted isolated server (`ALLES_DATA=…/alles3d_data PORT=8825 AUTH_ENABLED=false`), seeded
`notes/python.md` (+`tags: lang`) and `notes/cooking.md`, exercised every 3d endpoint with curl,
loaded the docs view in Playwright.

## What works (backend already in place)
- `GET /api/vault-md/ask?q=programming language` → ranked `sources` (python.md, score 0.1176;
  cooking.md correctly excluded). Reindexes the `doc` kind on first call if the index is empty.
- `GET /api/vault-md/ask?q=` → `{"sources":[]}` (no empty-query work).
- `POST /api/vault-md/clip` → creates `clips/<safe-title>.md` with `# title`, `source: <url>`, body.
  Title `Great Article!` → file `Great Article.md` (sanitised, `!` stripped).
- `POST /api/vault-md/base-cell` is async and calls `on_doc_saved(...)`, so a Base-cell edit can
  fire `doc_tag` automation rules (in-doc automations). `on_doc_saved` matches `enabled & trigger
  == doc_tag`, requires `#tag` in the note content, once-per-doc-per-rule, then `_fire` (create_task
  / create_note / push …).
- docs view loads with **0 console errors**; screenshot `audit-docs.png`.

## Bugs / gaps found
1. **`GET /api/vault-md/clipper-bookmarklet` returns a placeholder origin** —
   `fetch('YOUR_ALLES_ORIGIN/api/vault-md/clip', …)`. The bookmarklet is unusable as shipped; the
   origin must be derived from the request so the dragged bookmarklet posts back to this instance.
2. **No forms** — `POST /api/vault-md/form-submit` → 404. ROADMAP 3d calls for a form block that
   appends submissions to a note. Backend endpoint + helper missing.
3. **No charts** — query/dataview blocks render only as lists/groups (2b). ROADMAP 3d calls for
   bar/line/pie over a query/Base. `parse_query_spec` ignores a `chart:` directive; no chart render.
4. **No ask UI** — `/ask` has no front door in the docs toolbar (there is a per-doc `ai` edit
   button, but no vault-wide "ask your notes" panel).
5. **No web-clipper affordance** — even once the origin is fixed, there's nowhere in the UI to grab
   the bookmarklet.

## Plan (see docs/plans/3d.md)
- **3d-1 backend**: fix bookmarklet origin (request-derived); add `form-submit` + `append_form_row`
  helper; add `chart:` to `parse_query_spec` + pass through `chart`/group counts in `query_block`;
  lock in `/ask`, `/clip`, and the base-cell→automation path with tests.
- **3d-2 frontend**: docs "ask" panel (button + panel + ranked sources that open the note); charts
  on query blocks (`chart: bar|pie|line` → inline SVG); form blocks (```form fence → inputs →
  append a row); web-clipper section showing the draggable bookmarklet; version-stamp bump.

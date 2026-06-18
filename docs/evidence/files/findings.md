# files — audit findings (2026-06-18)

Booted isolated server (`:8799`, `ALLES_DATA`), drove `files.localhost:8799` in Playwright
(chromium, 1100×850), captured a screenshot per view + console log (`audit.json`, `console.log`)
and API dumps (`api_dumps.txt`).

## What was exercised (real data, real controls)
- **root listing** (`01-root.png`): smart-folder bar (recent / images / documents / large files),
  docs shortcut row ("15 notes · open in docs →"), real rows: notes(work,ideas) · photos · projects ·
  readme.txt(important,starred). All render.
- **subfolder nav** (`02-subfolder.png`): clicked `projects` → URL becomes `?p=projects`, breadcrumb
  becomes `files / projects`; clicking the `files` crumb returns to root (URL drops `?p`). Routing works.
- **sort toggle** (`03-sort.png`): clicked size → `size ↓`, date → `date ↓`, name → `name ↑`. The
  3-way sort with direction arrows works.
- **smart folder** (`04-smart-recent.png`): `recent` → 6 rows, crumb `files / recent`, back link works.
- **search** (`05-search.png`): typed `a` → 4 matching rows. Works.
- **preview** (`07-preview.png`): clicked a file → `.files-preview-card` opens. Works.
- **API** (`api_dumps.txt`): list root / list-by-size / smart recent·images·large·documents / search /
  tags / error path — all return sane JSON.

## Console / runtime
- **Zero console errors**, zero page errors across every view (`audit.json` → `console_errors: []`).

## The UI imbalance (the reported bug — confirmed)
Measured bounding boxes at root:
- `#files-breadcrumb` → y=109, height=29, text = **"files"** (lone, lowercase).
- `#files-sortbar` → y=138, height=29, text = "name ↑ / size / date".
- `sortbar.y (138) > breadcrumb.bottom (138)` → **the two are stacked on separate rows**.
- breadcrumb text at root == `"files"` → **redundant**: it just repeats the page title `files` sitting
  directly above it (see `01-root.png`: title "files", then a second lone "files", then the SORT row).

So under the header there are **two stacked, misaligned strips**: a pointless root breadcrumb and the
SORT row on its own line — exactly the "not in the same line / second 'files' is not necessary" complaint.

Secondary: `SORT` label starts further left (x≈10) than the breadcrumb/body content (x≈32), so even the
two strips don't share a left edge.

## Fix (one task → `files-ui-1`)
- `renderCrumb()` (files.js): at root (`_cwd === ''`) emit **nothing** instead of a lone `files` crumb.
  Keep the full `files / sub / sub` trail inside subfolders (the `files` crumb stays clickable→root).
- Wrap `#files-breadcrumb` + `#files-sortbar` in one flex `.files-subhead` row: breadcrumb left, sort
  pushed right (`margin-left:auto`), shared baseline, horizontal padding matching `.page-view-head/body`
  (`clamp(0.9rem,3vw,2rem)`). Drop the breadcrumb's old centered `max-width:760px;margin:0 auto`.
- Result: at root just the sort control on one clean right-aligned line (no redundant "files"); in a
  subfolder the path + sort sit on the **same** aligned row.

No backend change. Verified via Playwright structural assertions (≥8) + screenshot, zero console errors.

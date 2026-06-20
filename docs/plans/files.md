# Phase 12 — files (`files.js` + `routes/files.py` + `services/files_store.py`)

## Audit (2026-06-18)

Seeded a tree (projects/photos/notes + txt/csv/log/md/png/js) and drove files.localhost — 0 console errors.

Verified working (DO NOT rebuild): browse/navigate folders + breadcrumb; upload (100MB cap); mkdir;
rename (can move via full target path); delete (recursive); path-traversal-safe root; **content search**
(name + small-text-file body with snippets + match type); **rich previews** (image / pdf / video / audio
/ text) in a modal; docs-vault shortcut at root. So two items from the spec's example list — "search
inside contents" and "rich previews" — already exist; don't rebuild them.

Genuine gaps (modern file-manager features that fit single-user self-host):

1. **No smart/auto folders.** No "recent", "images", "large files", or by-type views — you can only walk
   the tree. These are the headline finder feature in the spec's list.
2. **No tags + colors.** No way to label a file/folder (macOS-Finder-style tag + color) or filter by it.
3. **No sort + no folder in the URL.** The list is always dirs-first-then-name; you can't sort by size or
   date. And opening a folder doesn't update the URL, so refresh / deep-link drops you back to root —
   violates the global routing rule.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **files-1 Smart folders.** GET `/api/files/smart/{kind}` aggregating across the whole tree:
  `recent` (mtime desc, last 30d), `images`, `large` (size desc), `documents` (text/office exts);
  shared `_walk()` honoring the safe root + skipping dotfiles, capped. UI: smart-folder shortcuts at the
  root that open a virtual results view. *Why: the spec's headline finder feature; "show me recent / big
  / all images" isn't answerable today.*
- **files-2 Tags + colors.** `FileTag` table (path, tags csv, color); GET/PUT `/api/files/tags?path=`,
  GET `/api/files/by-tag?tag=`, GET `/api/files/tags/all` (known tags + colors); entries in listings
  carry their tags/color. UI: tag/color affordance per row + a tag filter. *Why: labeling and finding by
  label is core to a real file manager.*
- **files-3 Sort + folder URL routing.** `sort` (name|size|mtime|type) + `order` (asc|desc) on
  `/api/files/list`, dirs-first preserved within a name sort; UI sort control; reflect the current folder
  in the URL (`?p=path`) so refresh / deep-link restores it (global routing rule). *Why: sorting is table
  stakes; folder-in-URL is the global rule.*

## Out of scope

PDF merge/rotate (needs a new pdf dependency — pypdf isn't installed; out of scope for a single-user file
manager), bulk multi-select, drag-to-move between folders, versioning, server-side thumbnails, zip/unzip.

---

# files — UI/UX polish (2026-06-18)

Re-audit evidence: `docs/evidence/files/` (findings.md + 6 screenshots + audit.json). Everything works
(nav, `?p=` routing, sort, smart folders, search, preview, zero console errors). Only defect: header
balance. Single UI task.

## files-ui-1 — merge breadcrumb + sort into one aligned row; drop redundant root crumb

**Problem (measured):** at root the breadcrumb is a lone "files" (y=109) duplicating the page title, and
the SORT row (y=138) sits on a separate line below it — two stacked, misaligned strips.

**Change:**
- `static/js/files.js` `renderCrumb()` — return early with empty breadcrumb at root (`_cwd===''`); keep
  the clickable `files / …` trail in subfolders.
- `static/index.html` — wrap `#files-breadcrumb` + `#files-sortbar` in `<div class="files-subhead">`.
- `static/style.css` — add `.files-subhead` (flex, one baseline, `clamp(0.9rem,3vw,2rem)` h-padding,
  sort `margin-left:auto`); strip the breadcrumb's centered `max-width/margin/padding`.

**Verify (Playwright `pw_files_ui1.py`, ≥8 assertions, RED before → GREEN after, screenshot, 0 console err):**
1. `root_no_redundant_crumb` — at root `#files-breadcrumb` text is empty (not "files").
2. `root_sort_present` — sort name/size/date buttons still visible at root.
3. `root_one_subhead_row` — breadcrumb + sortbar live in one `.files-subhead`, one baseline (|Δy|<6).
4. `subfolder_crumb` — inside projects, breadcrumb == "files / projects".
5. `subfolder_same_row` — in subfolder, breadcrumb and sortbar share one baseline (|Δy|<6).
6. `crumb_back_to_root` — clicking the `files` crumb returns to root (URL has no `?p`).
7. `sort_toggle_size` — clicking size activates it with a direction arrow.
8. `sort_toggle_date` — clicking date activates it.
9. `sort_right_aligned` — sortbar right edge is pushed right (right of the breadcrumb left edge).
10. `zero_console_errors` — no console/page errors; screenshot saved.

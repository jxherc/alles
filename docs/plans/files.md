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

# 6b audit — files: browse & dedup

No /duplicates, /preview, or /activity routes. python-docx IS installed (docx preview real);
openpyxl is NOT (xlsx preview falls back gracefully). files_store has abspath/listdir/smart/search
+ an is_img flag for thumbnails. Exact SHA-256 dedup only (perceptual out-of-scope). Grid view is
frontend-only. Plan: docs/plans/6b.md.

## Built + verified
- backend: `GET /duplicates` (SHA-256 grouping, skips empties + singletons, sorted by group size),
  `GET /preview` (docx -> real text/html via python-docx; xlsx -> graceful "openpyxl not installed";
  txt/md/csv/log/json -> raw text; else unsupported; 404 on missing), `GET /activity` (mtime-desc,
  `days`/`limit` filters).
- frontend: grid/list toggle (persisted in localStorage, real `<img>` thumbnails in grid),
  duplicates smart folder (per-group delete of a single copy), activity smart folder, office/text
  preview wired into the preview modal (docx renders its text). Bumped ?v=59 / sw v33.
- tests: `tests/test_files_browse.py` 13 GREEN; `tests/pw_files_browse_6b.py` 8/8 assertions.
- regression: `python tests/pw_regression.py 8852` -> 16/16 subdomains, 0 console errors
  (docs/evidence/6b/regression/). Full suite: 1354 OK.


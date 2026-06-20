# 6c audit — files: share

Ran against a fresh instance on :8853 (ALLES_DATA=alles6c_data).

## Already shipped (do NOT rebuild)
- **File share links + permission levels** — the 1a primitive already fully handles `kind="file"`:
  `POST /api/share {kind:file,ref,level}` mints a token, `GET /s/{token}` serves the file
  inline (`level=view`) or as an attachment (`level=download`). `files.js` already wires the per-file
  ⇗ button to `shareResource('file', path)`. Verified: mint -> `/s/{tok}` returned the file bytes.

## Genuine gaps (build these)
- **Folder share links** — `POST /api/share {kind:"folder"}` returns **400** (folder not in
  `share.VALID_KINDS`), and `/s/{token}` has no folder branch. Need: allow the `folder` kind, a
  read-only folder index page at `/s/{token}`, and a confined child route `/s/{token}/{subpath}` that
  serves files inside the shared folder (path-traversal safe, honoring view/download).
- **File comments** — `GET /api/files/comments` returns **404**; no `FileComment` model/routes.
  Mirror the 3e `DocComment` thread pattern (root + replies, resolve, delete) keyed on a files-relative
  path. Surface a comment count in the `/list` decoration + a 💬 thread popover in the UI.

## Plan
docs/plans/6c.md. Backend TDD in `tests/test_files_share.py`; UI in `tests/pw_files_share_6c.py`.

## Built + verified
- backend: `folder` added to `share.VALID_KINDS`; `/s/{token}` renders a read-only folder index;
  `/s/{token}/{subpath:path}` serves files inside the folder, confined (encoded `..` -> 404);
  `FileComment` model + `GET/POST /api/files/comments`, `POST .../{id}/resolve`,
  `DELETE .../{id}`; `/list` carries a `comments` count.
- frontend: ⇗ share button now on folder rows (mints a `folder` link); 💬 comment button on file
  rows with a count badge -> thread popover (add / reply / resolve / delete). Bumped ?v=60 / sw v34.
- tests: `tests/test_files_share.py` 15 GREEN; `tests/pw_files_share_6c.py` 8/8.
- regression: `pw_regression.py 8853` -> 16/16 subdomains, 0 console errors. Full suite: 1369 OK.

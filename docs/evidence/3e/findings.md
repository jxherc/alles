# 3e audit — inline comments

Booted `:8827` against the seeded 3d vault and probed for any existing comment feature.

## State
- `GET /api/vault-md/comments?path=…` → **404** (no route).
- `POST /api/vault-md/comments` → **404**.
- `static/js/vaultmd.js` contains **0** comment references — no UI, no model.
- No `Comment`/`DocComment` model in `core/database.py`.

3e is entirely net-new. Nothing to repair; build from scratch.

## Plan (docs/plans/3e.md)
Threaded comments anchored to a quoted span of a doc (Google-Docs / Notion style), stored in a new
`DocComment` table. Top-level comment = thread root; replies hang off it via `parent_id`. The anchor
is the quoted text; when the text still occurs in the note the marker highlights it inline, otherwise
the thread is shown as "orphaned" in the panel (no CRDT, no doc mutation).

- **3e-1 backend**: `DocComment` model; `POST/GET/DELETE /api/vault-md/comments`, reply, resolve;
  list grouped into threads (root + replies, resolved flag, anchor-orphaned flag). ≥8 unittest.
- **3e-2 frontend**: comments toolbar button + side panel; select text in preview → "comment"
  affordance; inline highlight on anchored spans; reply + resolve + delete; version bump. ≥8 pw.

# 1a — Share & Publish primitive — audit (2026-06-19)

Server booted isolated: `ALLES_DATA=…/alles1a_data PORT=8811 AUTH_ENABLED=false python app.py`.
Evidence here: `curl-share.txt`, `curl-gap-probes.txt`, `pw_audit.txt`, `view-*.png`, `pw_audit_1a.py`.

## What I exercised (real input)
- Seeded a real session ("Trip planning chat") with 2 messages, then drove the **existing** share
  flow end-to-end via curl (see `curl-share.txt`):
  - `POST /api/sessions/{sid}/share` → mints `{token,url:/s/{token}}`.
  - `POST` again → **idempotent**, returns the same token. ✓
  - `GET /s/{token}` → 200, renders a styled read-only HTML transcript with the real message text. ✓
  - `DELETE /api/sessions/{sid}/share` → `{ok:true}`; `GET /s/{token}` after → **404**. ✓
  - bogus token → 404; share on unknown session → 404. ✓
- Probed share on every other resource (`curl-gap-probes.txt`):
  `/api/vault-md/share`→404, `/api/files/share`→404, `/api/photos/share`→405,
  `/api/vault/share`→405, `/api/contacts/share`→405, `/api/calendar/share`→405, `/api/albums/share`→404.
- Drove 7 subdomain views with Playwright (`pw_audit.txt`, `view-*.png`): aide, docs, files, secrets,
  photos, contacts, calendar all load; **no share/publish affordance** on any of the six non-aide views
  (aide's share is a context-menu item `data-a="share"` in `app.js:_shareSession`, not a top-level button).

## Current state (confirmed in code)
- Only **`Session`** has sharing: `Session.share_token` column (`core/database.py:114`) +
  `routes/shared.py` (`POST/DELETE /api/sessions/{sid}/share`, `GET /s/{token}` at root, registered
  `app.py:543` with no prefix → public; auth middleware only gates `/api/*`).
- No generic share table; no other model has a token/public/visibility column.
- Docs are **file-based** (vault `.md` by path; no per-doc DB row except `DocRevision` keyed by path).
  → a doc share needs a `(kind, ref)`-keyed mapping, not a per-model column.
- Existing tests: `tests/test_api_shared.py` (`SharedApiTest`) — 4 cases; conventions to match.

## Bugs / imperfections found
- **None in the existing session-share flow** — it works correctly end-to-end.
- Non-1a, pre-existing (logged, not fixed here): docs view emits one `ERR_CONNECTION_CLOSED`
  (page-teardown/proxy artifact, per CLAUDE.md filtered as non-real); photos view emits one `401`
  (a photos sub-resource probe under AUTH disabled) — unrelated to sharing; will revisit in Stage 7.

## Gap → what 1a must build (build only this; don't rebuild session share)
A **generic** primitive so any resource can be shared/published read-only with one token scheme + one
viewer, reused later by docs-publish (3c), file links (6c), shared albums (7c), vault item share (9b),
booking pages (8b):

1. **`Share` table** `(token unique, kind, ref, level[view|download], created_at)` — `kind ∈
   {doc,file,photo,album,contact,event,session}`, `ref` = resource id or path. Keeps `Session.share_token`
   intact for back-compat.
2. **`services/share.py`** — `mint(kind, ref, level)` (idempotent per ref), `lookup(token)`,
   `revoke(token)` / `revoke_ref(kind, ref)`, `token_for(kind, ref)`.
3. **`/api/share`** — `POST {kind, ref, level?}` mint, `GET ?kind=&ref=` current token/null,
   `DELETE {kind, ref}` revoke (auth-gated; only the owner manages shares).
4. **Enhanced `GET /s/{token}`** — resolve generic table first (render by kind: doc→md→HTML page,
   file→inline/`download` stream, photo→image), else fall back to the existing session column. Public.
5. **UI** — a reusable `shareResource(kind, ref)` helper (mint + copy link + toast, reusing the existing
   clipboard pattern) wired as a **Publish/Share** affordance in the **docs editor head** and the
   **files row actions** (the two acceptance consumers); shows shared state + unshare.

## Planned tasks (TDD, ≥8 each) — see progress.json
- **1a-1** generic share backend (model + service + `/api/share` + `/s/{token}` viewer) — unittest (≥12).
- **1a-2** share UI (docs publish + files share via `shareResource`) — Playwright verify (≥8) + helper.

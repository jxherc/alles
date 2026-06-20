# Phase 7 — secrets / vault (`vault.js` + `routes/vault.py` + `services/crypto.py`)

## Audit (2026-06-18)

Verified working (DO NOT rebuild): AES master-password vault (unlock token + 10-min sliding window,
verifier-only on disk), password generator + strength meter, categories, create/list/reveal/patch/delete,
per-request token binding. Each entry was a single encrypted secret (name + username + one value).

Spec asks: richer item **types** and **fields** — password items need username/url/notes; card items need
cardholder/number/expiry/cvv. Confirmed gap: no item type; only one secret value per entry; no
structured/typed fields; UI form is single-secret.

## Tasks

- **secrets-1 Typed entries + structured encrypted fields.** `type` column (password|card|note); create/
  patch/reveal operate on an encrypted JSON `fields` blob (password→username/url/password/notes,
  card→cardholder/number/expiry/cvv/notes, note→notes); list exposes `type`; legacy bare-string secrets
  still decrypt. 9 tests. *Why: the spec's core ask.*
- **secrets-2 Type-aware UI + card meta.** Vault add/edit form adapts to the type; reveal shows each
  field with copy; card reveal returns brand/last4/luhn meta (helpers in `services/pwtools`). *Why: the
  typed fields need a real form + safe card display.*

## Out of scope

TOTP/2FA secrets, password-history, breach checks, attachments.

---

# secrets — UI/UX polish (2026-06-18)

Evidence: `docs/evidence/secrets/` (findings.md + 2 screenshots). User ask (Image #3): selecting a
category should auto-apply its field style, and creating a category should ask which fields it holds.

## secrets-cat-1 — per-category field schema

**Backend (`routes/vault.py`, schema in `settings.json` `vault_category_schemas`):**
- `_default_schema(cat)` infers fields (card / note / login / api-key / fallback).
- `GET /api/vault/categories` → `{categories, schemas:{cat:{fields}}}`.
- `PUT /api/vault/category-schema {name, fields}` persists one (drops unknown fields, 400 on empty name,
  403 when locked).

**UI (`static/js/vault.js`, `static/index.html`, `static/style.css`):**
- selecting a category shows exactly its schema fields (replaces the hardcoded regex + the fixed
  password/card/note TYPE segment); `type` inferred from the schema.
- "+ new category…" reveals a custom toggle-chip field-picker (username/password/url/notes/card — no
  native checkboxes); the chosen schema is PUT on add.
- reveal renders password + url + notes generically.

**Verify:** `tests/test_vault_category_schema.py` (13 cases, RED→GREEN) + Playwright `pw_secrets_cat.py`
(10/10 assertions, zero console errors, screenshots).

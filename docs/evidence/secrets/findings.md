# secrets / vault — audit findings (2026-06-18)

The isolated vault had a master password set during the prior build run that we don't hold, and its 2
seeded entries were encrypted with it (undecryptable). Since `:8799`/`alles_autorun_data` is throwaway
test data, the verifier was cleared and those 2 entries deleted so the new category-schema flow could be
exercised with fresh real input (unlock pw `autorun-vault`).

## Current behaviour (before fix)
- Add-bar had a fixed `password / card / note` TYPE segment that drove which fields showed.
- The **username** field appeared only via a hardcoded regex (`/password|login|account/i`) in
  `vault.js _onCatChange` — categories were plain strings with no per-category field config.
- url / notes were never collected from the form for credential entries (sent as empty).
- This is exactly the user's complaint (Image #3): selecting a category didn't change the field set, and
  creating a category never asked which fields it holds.

## Fix delivered (`secrets-cat-1`)
Per-category **field schema**, stored in `settings.json` as `vault_category_schemas` (same precedent as
`vault_verifier`):
- `_default_schema(cat)` infers fields for known categories (card→card; note→notes;
  password/login/account→username+password+url+notes; api key→password+url+notes; else password+notes).
- `GET /api/vault/categories` now returns `{categories, schemas:{cat:{fields}}}`.
- `PUT /api/vault/category-schema {name, fields}` saves one category's schema (unknown field names dropped;
  empty name → 400; vault-token required → 403 when locked).
- UI: selecting a category auto-shows exactly its fields (replaces the regex + the TYPE segment); choosing
  "+ new category…" reveals a **custom toggle-chip picker** (username / password / url / notes / card — no
  native checkboxes, per the no-native-UI rule) that's persisted on add. `type` is inferred from the
  schema; reveal renders password + url + notes.

## Evidence
- `cat-newpicker.png` — the new-category field-chip picker (password chip active).
- `cat-entries.png` — a custom "wifi" (password+notes) entry + a "GitHub" login revealing url + notes.
- Backend: `tests/test_vault_category_schema.py` (13 cases, RED→GREEN).
- UI: `pw_secrets_cat.py` — 10/10 assertions, **zero console errors**.

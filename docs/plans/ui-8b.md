# ui-8b — main vault / per-vault passwords + inline rename + change-password

A "main vault" concept made explicit, plus the ability to rotate any vault's password.

## Backend (`routes/vault.py`)
- `list_vaults` now returns `main: (v.id == 'default')` — the main vault is the default, opened by your
  master password; every other vault has its own password (verified at create/unlock).
- **`POST /api/vault/vaults/password`** `{new_password}` — re-keys the **currently-unlocked** vault:
  decrypts every entry **and attachment** with the old key and re-encrypts under the new one, computing
  all ciphertext *before* writing so a mid-way failure leaves the vault untouched. Swaps the verifier
  (and the legacy `vault_verifier` mirror for the default vault — i.e. this is "change master password").
  Hands back a fresh token bound to the new password.

## Frontend (`static/js/vault.js`)
- Manage panel: a **main / own-password badge** per vault + a help line explaining the model.
- **Inline rename**: click a vault name → edit in place → `PATCH /vault/vaults/{id}` on blur/enter.
- **Change password**: on the unlocked vault's row, a "change master password" / "change password" button
  opens a new+confirm prompt, calls the re-key endpoint, and re-binds the session token.

Tests: `tests/test_vault_main_rekey.py` (9: main flag, own-password unlock, entry + attachment re-key,
change-master, empty/unauth rejects, rename) + `tests/test_vault_main_ui.py` (6 frontend contract) +
`docs/evidence/ui-8b/verify.py` (live: badge, help, inline rename, change-master → old fails / new works).

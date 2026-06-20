# Vault / Secrets Audit Findings — 9c
Date: 2026-06-20
Server: PORT=8801, ALLES_DATA=.tmp_audit9c (clean/isolated), AUTH_ENABLED=false
Test method: PowerShell curl-style API + Playwright UI screenshots

---

## What was exercised

1. Full unlock/lock/re-unlock cycle including wrong-password rejection
2. Create entries of all 4 primary types: login (password), card, apikey, note
3. GET /api/vault list, GET /api/vault/{id}/reveal for each type
4. GET /api/vault/categories
5. GET /api/vault/watchtower (seeded weak + reused + HIBP-breached entries)
6. POST /api/vault/lock → confirmed 403 on subsequent requests
7. Password strength endpoint + password generator
8. UI screenshots: lock screen, unlocked list, form (login type dropdown open), form (card reveal), reveal (login + card), watchtower panel, after-lock

---

## Bugs and Issues

### BUG 1: Category/type namespace mismatch (JS vs backend)
Severity: Medium

The JS _saveForm sends category: TYPE_BY_KEY[typeKey]?.label || typeKey — title-cased:
- "Login" (not "password")
- "API key" (not "api key")
- "Credit card" (not "card")

The backend _BASE_CATS = ["password","api key","card","note","general"] uses different naming.

Reproduction: POST /api/vault with {"name":"X","type":"login","category":"Login",...}
then GET /api/vault/categories returns both "Login" AND "password" as separate categories.
Over time: category list fills with JS-generated title-case duplicates alongside the old lowercase ones.

---

### BUG 2: value field is empty for apikey, card, note types
Severity: Low

GET /api/vault/{id}/reveal returns "value": "" for apikey, card, note entries.
Only login entries get value = fields.password. The JS _primarySecret() handles this correctly
via the PRIMARY map, so copying works. But the API shape is inconsistent and confusing.

---

### BUG 3: Watchtower does not scan apikey field
Severity: Low

Watchtower reads only fields.get("password"). An apikey entry with fields.apikey is invisible —
not checked for weak/reused/breached. Reused or breached API keys won't be detected.

---

### BUG 4: POST /api/vault/lock is a global token nuke
Severity: Medium for 9c multi-vault work

_unlock_tokens.clear() wipes every active token for every session. Two browser tabs unlocked =
locking from one logs out both. For 9c Travel Mode where a secondary vault may need to stay
unlocked while the main vault locks, this must become per-vault-id scoped.

---

### BUG 5: Card number shown unmasked in edit form after reveal
Severity: UX concern

When opening a card entry and clicking "show" on the card number field, the full PAN
(4242424242424242) appears in plaintext. The reveal API correctly returns card.masked
("••••••••••••4242") but the edit form fills the raw number into the input and doesn't
use the masked version. Screenshots: reveal-card.png.

---

### BUG 6: No search/filter on vault list
Severity: UX gap

No server-side filtering, no client-side search box. With many entries this becomes unworkable.
Not a 9c regression — a pre-existing missing feature.

---

## What works well

- Lock/unlock: wrong password → 401, locked requests → 403, correct password → 200 + token.
- TTL sliding window: 10-min idle timeout, reset on each use.
- Encryption: AES-256-GCM, PBKDF2-SHA256 260k iterations, per-entry random salt. Strong.
- Watchtower: correctly detected weak (score 0), reused (exact match), HIBP breached (123456 → 210M).
- Card metadata: brand detection, last4, Luhn validation working.
- Password generator returns cryptographically random passwords + entropy score.
- All 8 entry TYPES render correctly in UI: Login, API key, Credit card, Secure note, Identity, Bank account, SSH key, Software license.
- Zero browser console errors across all UI flows.
- Subdomain routing: secrets.localhost:8801 correctly scoped to vault view.

---

## Key Facts for 9c Implementation

### How vault.js stores the token (client-side)

vault.js lines 5-6:
  let _unlocked = false;
  let _token = null;  // module-level variable — JS memory only, no localStorage

No persistence: closing tab or reload = must re-unlock.
_vfetch() at line 82 attaches it as X-Vault-Token header, uses only the single _token.
For 9c multi-vault: needs _tokens = {} (vault_id → token) or equivalent map.

### How the lock screen works

NOT a separate page/route. It's a plain <div id="vault-locked"> in index.html at line 618,
toggled by loadVaultView() via display style. The adjacent <div id="vault-unlocked"> is shown/hidden.
No URL change, no navigation. Single lock screen for the single vault.

For 9c multi-vault: needs vault-selector UI before or alongside the lock screen.
The current single-div pattern does not support per-vault lock states without restructuring.

### Where the create/edit form lives

openVaultForm() in vault.js line 137: dynamically creates a .modal-overlay.vault-modal appended
to document.body. Pure in-memory modal. The TYPES array at line 47 drives the dropdown.
_renderFields() at line 314 generates field inputs from the selected type's field schema.
Share button (#vf-share) appears only in edit mode.

### Categories endpoint drift (relevant to 9c)

/api/vault/categories returns old vocabulary (password, api key, card, note, general).
New entries use new type keys (login, apikey, card, note, identity, bank, ssh, license).
The category stored on entries is mostly "general" — the endpoint is largely stale.
9c should either retire it in favor of the client-side TYPES[] or fix the aliasing.

### unlock response already returns vault_id

POST /api/vault/unlock returns {"token":"...","vault_id":"default"} — the vault_id field
is already there as a stub. Client (vault.js) ignores it. When 9c implements multi-vault,
the client must read vault_id and store tokens per-vault-id.

---

## Screenshots

- lock-screen.png — initial lock screen (padlock icon, password input, unlock button)
- list.png — unlocked list: 4 entries shown with type badges (Secure note, API key, Credit card, Login)
- form-password.png — new-entry modal with type dropdown open, Login type options visible
- form-card.png — all 8 type options visible in dropdown (Login/API key/Credit card/Secure note/Identity/Bank account/SSH key/Software license)
- reveal.png — edit modal for GitHub entry: password revealed (Sup3r$ecr3t!99), TOTP field, URL, notes, attachments section visible
- watchtower.png — watchtower panel showing all clear (breached 0, reused 0, weak 0) for the initial seeded entries
- reveal-card.png — edit modal for Visa Infinite: card number 4242424242424242 shown in plaintext after clicking show, expiry/CVV in half-width fields
- after-lock.png — lock screen after clicking lock from UI (same UI as initial lock screen)

---

## 9c implementation + post-microversion regression (resumed run)

**Built (all TDD, RED→GREEN, ruff + node --check clean):**
- **9c-1 multiple vaults + Travel Mode** — `Vault` model + `VaultEntry.vault_id` (default-vault
  migration absorbs the legacy `vault_verifier` + pre-existing entries). Per-vault unlock
  (`/vault/unlock {vault_id}`), `/vault/vaults` CRUD, `/vault/travel-mode`. Travel Mode hides and
  refuses unlock of vaults not marked travel-safe. List + watchtower scoped to the unlocked vault.
  12 unit tests (`tests/test_vault_multi.py`).
- **9c-2 WebAuthn biometric unlock** — `services/webauthn.py` (challenge + ES256/SPKI assertion verify,
  no CBOR), `WebAuthnCredential` model, register/credentials/challenge/unlock endpoints. Master pw
  wrapped per-vault under a per-install server key (`vault_biometric_key`) so a verified assertion
  releases an unlock token. 12 unit tests (`tests/test_vault_webauthn.py`).
- **9c-3 frontend** — vault switcher dropdown, create-vault, Travel-mode toggle, manage-vaults modal
  (per-vault travel-safe + delete), enable-biometric, lock-screen biometric-unlock. 10 Playwright
  assertions (`tests/pw_vault_9c.py`), all pass, 0 console errors. Cache stamps bumped to v70 / SW v44.

**Regression:** `tests/pw_regression.py` — all 16 subdomains load, 0 console errors
(`docs/evidence/9c/regression/`). Full suite `python -m unittest discover -s tests`: 1548 tests OK.

**Test-hardening fixes made (pre-existing, surfaced by the full-suite run):**
- `test_journal_moods` / `test_journal_heatmap` didn't isolate settings, so a real
  `data/settings.json` journal passcode locked them out. Added a tempfile `_SETTINGS_FILE` patch
  (matches the repo's stated test convention) → hermetic.
- `test_timeline_summary.test_busiest_day` assumed local date == UTC date; tasks are dated by
  `created_at` (utcnow) while money used `date.today()` (local), so near midnight UTC the task fell
  on a different day. Anchored the seed + assertion to `datetime.utcnow().date()` → deterministic.

**Deferred (pre-existing, low severity, outside 9c "vaults & unlock" scope — logged, not fixed):**
- Category/type namespace pollution: the create form sends `category` = the type's title-cased label
  ("Login") while the backend base categories are lowercase ("password"), so each UI-created entry
  adds a near-duplicate category. Candidate for a future secrets-polish pass.
- Watchtower scans only `fields.password`, not `apikey` — reused/breached API keys are invisible.
- `reveal.value` only echoes `fields.password` (empty for card/note/apikey) — minor API-shape wart.
- `POST /vault/lock` clears all tokens globally (acceptable single-user semantic; noted for multi-vault).

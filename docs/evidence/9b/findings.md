# 9b — secrets: attachments + per-item share — findings

Audited the vault by running an isolated server (`ALLES_DATA=/tmp/alles9b PORT=8869`) + Playwright.

## Built (gaps only)
- **9b-1 encrypted attachments** (`services/crypto.py`, `core/database.py`, `routes/vault.py`):
  `encrypt_bytes`/`decrypt_bytes` (master-pw AES-GCM for binary); `VaultAttachment`; upload (encrypts at
  rest under `<data>/vault_attachments/{id}.enc`), list, download (decrypts), delete — all vault-gated.
- **9b-2 per-item share** (`services/crypto.envelope_encrypt/decrypt`, `VaultShare`, `routes/vault.py`,
  `routes/shared.py`): mint encrypts the revealable fields with a **fresh random key** (not the master pw);
  only the ciphertext + token are stored; the key is returned and travels in the URL **fragment** (server
  never sees it). Public `GET /sv/{token}/data` returns the blob; `GET /sv/{token}` is an HTML page that
  decrypts in the browser (WebCrypto AES-GCM); `DELETE /vault/{id}/share` revokes.
- **9b-3 frontend** (`static/js/vault.js`, `index.html`, `style.css`, `sw.js`): the entry form gains an
  attachments list (upload / download / remove) and a 🔗 share action that mints + copies the link.
  Stamps → v69 / SW v43.

## Exercised with real input
- Unit: `test_vault_attachments` (9/9) incl. ciphertext-on-disk check (plaintext never on disk),
  size recorded, 403 without unlock. `test_vault_share` (9/9) incl. blob is ciphertext, Python-side
  envelope decrypt roundtrip, revoke→404, key-not-stored-server-side, idempotent mint.
- UI (Playwright `pw_vault_share_9b`, 8/8): upload shows, download, remove, share button, mint link with
  `#key`, **public page decrypts read-only** (see `public-share.png`), revoked link no longer resolves.

## Bugs found + fixed (real, caught by the UI test)
1. **Service-worker write-queue swallowed vault POSTs** (`/api/vault` JSON unlock/create got `{queued}` on
   first load) → added `/api/vault` + `/api/carddav` to the SW `NOQUEUE` list.
2. **Revoked share resolved from cache** — the SW cached `/sv/` GETs and chromium's HTTP cache held the blob,
   so a revoked link still decrypted. Fixed two ways: SW now never caches `/s/` or `/sv/`, and the share
   endpoints send `Cache-Control: no-store`. Verified backend revoke → 404 + UI revoked link shows nothing.

## Crypto note
The master password never leaves the box; share keys are random per-item and live only in the URL fragment
(never sent to the server). Attachments are AES-GCM at rest.

## Evidence
`pw_vault_share_9b.txt` (8/8), `public-share.png`. Unit: 18 tests across two files.

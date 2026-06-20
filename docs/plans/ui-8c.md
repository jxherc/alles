# ui-8c — authenticator-app (TOTP) 2FA + biometrics-vs-passkey explainers

Vault unlock 2FA was WebAuthn-only. Added a TOTP/authenticator-app second factor alongside passkeys.

## Backend (`services/pwtools.py`, `routes/vault.py`)
- pwtools: `totp_secret()` (random base32), `totp_verify(secret, code, window=1)` (±1 step skew),
  `totp_uri()` (otpauth provisioning URI).
- `POST /vault/2fa/totp/setup` → fresh secret + otpauth URI (not stored until proven).
  `POST /vault/2fa/totp {secret, code}` → verifies the code, stores the secret, turns the 2FA gate on.
  `DELETE /vault/2fa/totp` → removes it (drops the gate if no factor remains).
- `GET /vault/2fa` now also returns `totp`. Unlock now hands back `methods` (`passkey` and/or `totp`)
  when a second factor is required. `POST /vault/unlock/2fa/totp {password, code}` mints the token.

## Frontend (`static/js/vault.js`)
- 2FA panel lists both methods (passkey + authenticator app) with enrol/remove + an on/off gate, an
  explainer that **biometric unlock replaces the password** while **passkey 2FA is an extra factor**.
- TOTP enrol modal shows the secret + a confirm-code box. `_doUnlock` handles `requires_2fa`: prompts
  for the 6-digit code and unlocks via the TOTP endpoint.

Tests: `tests/test_vault_totp_2fa.py` (12: helpers + setup/enable/disable/status + unlock gating) +
`tests/test_vault_totp_ui.py` (6 frontend contract) + `docs/evidence/ui-8c/verify.py` (live: enrol with a
computed code, then a locked unlock demands the code — wrong rejected, right unlocks).

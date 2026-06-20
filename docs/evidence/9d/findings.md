# 9d — passkeys & autofill: implementation + regression

Built depth-first, strict TDD (RED→GREEN), ruff + node --check clean.

- **9d-1 passkey storage + use** — `services/passkey.py` (ES256 keypair + WebAuthn-style sign,
  round-trips through `webauthn.verify_assertion`). Passkey vault items (`type:"passkey"`) hold the
  private key encrypted; `POST /vault/passkey/new`, `GET /vault/passkeys`,
  `POST /vault/{id}/passkey/sign` (private key never leaves the box). 11 unit tests.
- **9d-2 hardware-key 2FA gate** — `WebAuthnCredential.role="2fa"`, per-vault `require_2fa` setting.
  When on (and a key is registered), `/vault/unlock` withholds the token and returns a challenge;
  `/vault/unlock/2fa` mints the token only after BOTH the password and a valid security-key assertion.
  No-credential-no-lockout guard. 10 unit tests.
- **9d-3 browser-extension autofill** — `GET /vault/match?domain=` (host-matched logins, www/subdomain
  aware, unlock-gated) + an MV3 `extension/` (manifest, content/background/popup) that pastes an unlock
  token and fills logins. 10 unit/file tests.
- **9d-4 frontend** — passkey item type (create mints server-side, lists with a Passkey label),
  require-security-key (2FA) toggle + register-security-key in the manage-vaults modal, autofill
  extension affordance. 8 Playwright assertions, 0 console errors. Stamps bumped v71 / SW v45.

**Regression:** all 16 subdomains load 0 console errors (`docs/evidence/9d/regression/`).
Full suite `python -m unittest discover -s tests`: 1579 tests OK (skipped=1).

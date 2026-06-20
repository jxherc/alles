# ui-8c — TOTP 2FA (findings)

## Audit
Vault 2FA was passkey/WebAuthn-only and unexplained; `_doUnlock` didn't even handle a `requires_2fa`
response. TOTP existed only for entry codes, not for unlock.

## Fix
Added TOTP helpers (secret/verify/uri), setup/enable/disable/unlock endpoints, and a `methods` array on
the unlock challenge. The 2FA panel now enrols an authenticator app (shows the secret + confirm code),
lists both methods, and explains biometric-unlock (replaces the password) vs passkey-2FA (extra factor).
`_doUnlock` prompts for the code when a second factor is required.

## Bug caught in verify
`_setupTotp` fetched the setup endpoint with the default GET → 405, so the secret came back empty and
enrolment always failed. The Playwright verify surfaced it (empty `#totp-secret` + console 405). Fixed to
POST.

## Verify
`verify.py` (fresh server) enrols TOTP with a code computed from the app's own `totp_now`, then locks and
unlocks: the code prompt appears, a wrong code is refused, the correct code unlocks. 0 console errors.

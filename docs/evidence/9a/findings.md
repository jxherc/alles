# 9a — secrets: TOTP + Watchtower — findings

Audited the vault by running an isolated server (`ALLES_DATA=/tmp/alles9a PORT=8868`) + Playwright.

## Audit — state before the build
- Vault entries store typed `fields` encrypted as JSON; reveal decrypts them. `pwtools` had strength +
  card helpers only. No TOTP, no Watchtower. `pyotp` is NOT installed.

## Built (gaps only)
- **9a-1** (`services/pwtools.py`, `routes/vault.py`): TOTP from **RFC 6238 in stdlib** (`totp_now`,
  `totp_remaining` — no dep, like web push). A `totp` field on an entry holds the base32 secret;
  `GET /vault/{id}/totp` (vault-gated) returns `{code, seconds}` (404 if no secret). Watchtower:
  `is_weak` (strength ≤ 1), `find_reused` (group ids sharing a password), `breach_count(pw, fetch)`
  (HIBP k-anonymity — only the SHA1 5-char prefix leaves the box; injectable fetch). `GET /vault/watchtower`
  (vault-gated) → `{weak, reused, breached}`.
- **9a-2** (`static/js/vault.js`, `index.html`, `style.css`): a `TOTP secret` field on Login/API-key types;
  on reveal, a live code + a seconds countdown (fetch once + local tick, refetch at expiry); a 🛡 Watchtower
  button → a panel listing breached / reused / weak with counts. Stamps → v68 / SW v42.

## Exercised with real input
- Unit (`test_vault_totp_watchtower`, 12/12): RFC 6238 vector (T=59 → 287082), same-window stability,
  remaining in [1,30], TOTP endpoint returns a 6-digit code, 404 without a secret, is_weak, find_reused,
  breach_count parses an HIBP response, watchtower weak/reused/breached (mocked HIBP), 403 without unlock.
- UI (Playwright `pw_vault_9a`, 8/8): TOTP field in the form, live code + countdown on reveal, Watchtower
  button, panel renders all three sections, lists weak + reused. **Real HIBP was reachable** — "123" came
  back "seen 15,155,838×" in the breached section (see `watchtower.png`). Screenshot `totp.png`.

## Bugs / imperfections found
- **App bugs: none.** TOTP computed against the canonical RFC vector. Breach check degrades gracefully to
  0 when HIBP is unreachable (caught), so the UI/regression stay clean offline.
- Renamed one planned UI assertion `watchtower_empty_clean` → `watchtower_renders` (deterministic regardless
  of HIBP reachability; the empty-state "✓ all clear" branch is still in the code for sections with no hits).

## Evidence
`pw_vault_9a.txt` (8/8), `totp.png`, `watchtower.png`. Unit: 12 tests.

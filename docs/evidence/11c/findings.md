# 11c — Unification: alles↔aide cross-app audit + polish

ROADMAP 11c (S). Acceptance: a Playwright sweep cross-navigates all subdomains with one login,
0 console errors; subdomain scope + SSO handoff + cross-jump verified.

## Audit
Auth/SSO machinery already correct — no product code needed (the ROADMAP itself notes "the audit
found none in code; this hardens it as the suite grows"). Confirmed by reading:
- `core/auth.py` — session token store, `make_handoff`/`redeem_handoff` (24-byte code, 30s TTL,
  single-use via `.pop`), login throttle.
- `routes/auth.py` — `/login` `/logout` `/me` `/handoff` `/redeem` `/config`; `_cookie_domain_kw`
  leaves the cookie host-only on localhost (Domain=localhost wouldn't reach *.localhost).
- `app.py:493` `TokenAuthMiddleware` gates `/api/` (except `/api/auth/*`) when `auth_enabled()`.
- `static/js/subdomain.js` — `SUBDOMAIN_VIEWS` host→app map; `app.js` `applySubdomainScope()`.
Existing tests covered the handoff dict mechanics + password/config; the gaps were *integration*.

## Built (tests only — hardening)

### 11c-1 backend SSO + scope over HTTP (tests/test_sso_11c.py — 14/14)
Drives the real app with AUTH_ENABLED flipped per-test (read at call time) + isolated settings.
Covers /me shape (lock off/on, authed/unauthed), login + wrong password, handoff requires auth,
the **full login→handoff→redeem→session round-trip via a second client**, single-use, bad code,
expired code, middleware gating /api/ (and /api/auth/* exempt, open when disabled), logout
revokes, and the host-only (no Domain=) localhost session cookie.

### 11c-2 frontend cross-app sweep (tests/pw_unify_11c.py — 10/10, 16 hosts)
One server, walks every SUBDOMAIN_VIEWS host. Asserts each boots (no login-mode), carries the
right scope class (apex→is-hub, aide→is-aide, the other 14→is-subapp), the right `body.dataset.app`
is active, and logs 0 console errors. Plus: sidebar shows on aide / hidden on subapps, the crumb
shows on subapps, and clicking the crumb cross-jumps back to the hub (hostname → localhost).

## Regression
`tests/pw_regression.py 8880` — ALL CLEAN (0 errors every view).

## Suite
`python -m unittest discover -s tests` → Ran 1727 tests, OK (skipped=1) (+14 vs 11b's 1713).

## Verdict
11c done: cross-app scope, SSO handoff, and cross-jump are now covered end-to-end (HTTP + 16-host
Playwright sweep), 0 console errors.

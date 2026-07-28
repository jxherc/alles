# Afterlife Phase 9 - distribution and browser access

- **Status:** delivered and verified 2026-07-20
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** [`phase-08-specialist-app-consolidation.md`](phase-08-specialist-app-consolidation.md) delivered and verified
- **Design review:** [`../phase-09-design-review.md`](../phase-09-design-review.md)
- **Checkbox rule:** `[x]` means implemented and freshly tested with throwaway data. `[ ]` means it is still open.

## Goal

Make a normal macOS or Linux installation own its runtime, launcher, service, setup state, updates,
rollback, and uninstall boundary. Restore browser filling only through a paired, revocable browser
identity and a short-lived Passwords unlock that is restricted to the selected credential and exact
top-level site.

The owner explicitly waived the standalone mockup requirement for this phase. The real setup and
Passwords additions still use the documented KOKUEN controls and must pass the complete rendered QA
gate before this phase can be marked delivered.

## 9A - installer, setup, updates, and uninstall

- [x] Create a versioned Alles-owned runtime and private Python environment without modifying system
  Python packages.
- [x] Generate and verify a user launchd or systemd-user service definition through the existing
  ownership registry.
- [x] Install the `alles` launcher automatically and refuse to overwrite an unowned launcher,
  service, runtime, or manifest.
- [x] Keep program releases, private app data, visible Vault/Files locations, logs, and transient
  update state in explicit separate paths.
- [x] Persist first-run progress on the server after every step so another browser can resume it.
- [x] Cover Basics, Access, Files, AI/Search, and Protection with a cancel/resume path and honest
  partial/error states.
- [x] Expose **Keep the vault inside the Alles folder** as a default-on KOKUEN switch and preview the
  exact Vault and Files paths before creation.
- [x] Leave an existing vault unchanged unless the owner explicitly selects it.
- [x] Detect Obsidian and install or update the Alles companion only after exact approval; never
  silently create or modify `.obsidian` content in a connected vault.
- [x] Stage a candidate release and its dependencies outside the live release, compile and probe it,
  create an encrypted pre-update backup, switch atomically, health-check, and retain one rollback.
- [x] Roll back the exact paired code release and data backup after a failed switch or explicit
  rollback request.
- [x] Uninstall only verified Alles-owned runtime, service, and launcher files while preserving all
  personal data by default.

**9A gate:** clean install, upgrade, failed upgrade, manual rollback, interrupted-state recovery, and
uninstall-keep-data pass for simulated launchd and systemd-user layouts. A native current-host gate
must also pass without writing to the owner's normal Alles data.

## 9B - Passwords browser extension

- [x] Keep `/api/vault/match` as a permanent rejected legacy-token path that revokes the exact pasted
  vault unlock token and returns no credential data.
- [x] Add short-lived, rate-limited browser pairing requests that never ask for or accept a raw vault
  unlock token from the extension.
- [x] Store only a hash of the persistent narrow browser secret and show the paired browser in
  Passwords with its name, created time, last use, and lock state.
- [x] Require an unlocked Passwords vault and explicit owner approval to pair or unlock a browser.
- [x] Keep browser unlock sessions in server memory and extension session storage so browser restart,
  server restart, inactivity, explicit lock, or computer lock removes fill authority.
- [x] Revoke a connected browser immediately and reject every old device or session credential after
  revocation.
- [x] Ask for the chosen Alles origin and `activeTab` access only; do not request permanent all-site
  read access or ship a content script that runs on every page.
- [x] Match the exact normalized scheme, host, and effective port. Reject HTTP except loopback,
  lookalike hosts, cross-origin frames, and scheme or port downgrades.
- [x] Return safe matching metadata first, then release only the credential the owner selects.
- [x] Fill only the top-level current tab, never submit, and refuse password-change/multi-password
  forms or a frame whose origin differs from the reviewed target.
- [x] Add Connected browsers, pair/unlock approval, immediate revoke, and visible error/recovery states
  to Passwords using KOKUEN controls.

**9B gate:** pair, fill, explicit lock, inactivity/computer lock, browser restart, server restart,
revoke, top-level frame restriction, HTTP downgrade, lookalike host, wrong port, rejected legacy token,
and clean extension permission tests pass before the extension is described as available.

## Final verification

- [x] Focused installer, update, rollback, uninstall, setup, pairing, matching, release, and migration
  tests pass with throwaway roots.
- [x] The real setup and Passwords flows pass desktop/mobile, keyboard, 200 percent zoom, both themes,
  reduced motion, focus return, overflow, target-size, contrast, and clean-console checks.
- [x] The unpacked Chromium extension passes a real current-tab pair/fill/lock/revoke browser gate
  against an isolated Alles server and synthetic login page.
- [x] Full Python and JavaScript suites pass.
- [x] Repository-wide Ruff lint/format and diff integrity pass.
- [x] The real Git index remains empty; no commit or push is made.
- [x] A final requirement-by-requirement audit records honest checked and unchecked status.

**Final audit:** 30 checked rows, 0 unchecked rows. The frozen-source gate ran 4,981 Python tests
(4,976 passed and 5 skipped) and 422 JavaScript tests with no failures. The real setup/Passwords,
unpacked extension, native current-host, and bidirectional Home/Docs gates all passed against owned
throwaway data.
Ruff lint, Ruff format across 908 Python files, diff integrity, and the empty Git index also passed.

Autoreview is explicitly outside this delivery scope by owner direction. No clean-autoreview claim is
required or will be made.

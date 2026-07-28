# Afterlife Phase 11 - post-development review and handoff

- **Status:** delivered and verified 2026-07-21; approved remaining-gap work completed 2026-07-22;
  40/41 original requests satisfied, 1 honestly open
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** [`phase-10-localization-release-hardening.md`](phase-10-localization-release-hardening.md) delivered and verified
- **Handoff record:** [`../final-review.md`](../final-review.md)
- **Checkbox rule:** `[x]` means current implementation and fresh evidence agree. `[ ]` means open.
- **Delivery boundary:** no mockup, autoreview, owner-data access, commit, or push.

## Goal

Perform the final requirement, code, security, privacy, migration, dependency, data-loss, lifecycle,
browser, accessibility, and regression review against the real `dev-afterlife` worktree. Fix confirmed
in-scope blockers, preserve unrelated dirty work, and leave an honest checked/unchecked handoff.

## 11A - source and requirement reconciliation

- [x] Locate and read the authoritative 41-request `reminders and notes.md` brainstorm source.
- [x] Record all 41 requests in `final-review.md` without treating its planning checkmarks as delivery.
- [x] Map every request to current implementation, specifications, focused tests, rendered evidence,
  and any honest limitation or superseding owner decision.
- [x] Reconcile the final-acceptance list in `design.md` with the same evidence.
- [x] Leave no original request unmapped.

## 11B - detailed implementation review

- [x] Review route and service entry points for authentication, authorization, origin, network, and
  secret-boundary defects.
- [x] Trace untrusted input through SQL, subprocess, filesystem, archive, Markdown/HTML, URL-fetch,
  connector, Files, Docs, Finance, Passwords, Aide, and managed-service sinks.
- [x] Review migrations for additive behavior, idempotence, rollback/recovery, legacy-fixture parity,
  and data-loss risk.
- [x] Review backup/restore, storage operations, Actual cutover, native update, and uninstall behavior
  for interruption, concurrency, and original-data preservation.
- [x] Audit Python, mobile, vendored, managed, and packaged dependencies plus generated notices.
- [x] Run a tracked-file secret/exposure scan and self-verify every candidate before reporting it.
- [x] Record every finding with severity, confidence, affected path, evidence, disposition, and test.

## 11C - lifecycle, recovery, and platform proof

- [x] Verify clean install on supported macOS and a real Linux container with throwaway data.
- [x] Verify upgrade, failed upgrade, rollback, and uninstall-keep-data.
- [x] Verify encrypted local backup/restore plus interrupted recovery and fail-closed maintenance.
- [x] Verify external Vault, Actual, local/WebDAV/S3 Files state, and managed-service recovery within
  their documented synthetic/protocol boundaries.
- [x] Verify browser-extension pairing, restart, lock, revoke, frame, downgrade, and lookalike-host
  boundaries.
- [x] Record physical-host, container, simulated-service, and unavailable-owner-endpoint limits.

## 11D - real browser and interface proof

- [x] Use a non-conflicting port and throwaway `ALLES_DATA` for all browser checks.
- [x] Verify representative desktop, narrow desktop/tablet, phone, and 200 percent zoom layouts.
- [x] Verify pointer, keyboard, focus order/return, custom controls, both themes, and reduced motion.
- [x] Verify loading, empty, partial, offline, permission, disabled, long-content, interrupted, error,
  retry, and recovery states where applicable.
- [x] Inspect browser console, page errors, failed requests, clipping, overflow, overlap, and cut-off
  content.
- [x] Re-check every applicable design-system QA and anti-slop rule against fresh rendered evidence.

## 11E - final regressions and handoff

- [x] Run focused tests for every confirmed fix and prove each regression fails without the fix when
  practical.
- [x] Run the complete Python and JavaScript suites from the final worktree state.
- [x] Run repository Ruff lint/format, generated-artifact determinism, whitespace, Git-index, and
  private-file boundary checks.
- [x] Record exact commands, versions, counts, outputs, evidence paths, open risks, and intentional
  deferrals in `final-review.md`.
- [x] Update shipped documentation only where implementation and fresh evidence agree.

## Final gate

- [x] All 41 original requests and every final-acceptance row have a checked or honestly unchecked
  status with implementation and evidence.
- [x] No unexplained failing check or missing required end-to-end evidence remains.
- [x] No unresolved critical or high-severity review finding remains.
- [x] Owner data is untouched and the real Git index remains empty.
- [x] No autoreview, mockup, commit, or push is performed.

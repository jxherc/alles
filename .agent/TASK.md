# current mission

## goal
Audit and remove proven obsolete code and UI, repair confirmed broken paths, and publish a verified cleanup to dev-afterlife.

## requirements
- Preserve owner data, public API and deep-link compatibility, active specialist modules, and recovery code.
- Use owned temporary data. Preserve the pre-existing untracked alles-full-review.md.
- Existing session authorizes implementation and publication; no product rework or framework migration.

## plan
1. Trace runtime dependencies and repository-wide symbol references; classify deletion candidates.
2. Remove proven dead implementations and their obsolete coverage; retain or move coverage for current behavior.
3. Repair reproduced behavior regressions, refresh generated inventories, and verify current rendered app.
4. Run full local checks, commit, push, and wait for the exact GitHub run to succeed.

## audit findings
- Four JS modules are unreachable from the app's module graph: files.js, research.js, ragquery.js, aidebehavior.js.
- Old research card CSS and disconnected behavior hooks exist only for those retired modules.
- Seven private Python helpers and several JS helpers have no repository consumers.
- The current Files module ignores saved sort/order deep-link parameters; its source contract checks retired files.js.
- The live-voice button only displays a ready toast; it does not establish a voice connection.
- Primary/specialist screens, old URL aliases, APIs, persisted schema/migrations, safety limits and external adapters are live.

## completed
- Removed the four disconnected JS modules, dead helpers/callbacks, seven private Python helpers,
  nonfunctional live-voice action, obsolete research/Files CSS, and retired UI-only test scripts.
- Restored current Files sort/order links and missing WebDAV/S3 icons.
- Reproduced and fixed mobile breadcrumbs wrapping outside the header and transfer-panel clipping
  beside the shell rail under reduced motion.
- Added current-module inventory and real-browser cleanup regressions; refreshed control census.
- Documented audit boundaries in docs/cleanup-2026-09-21.md; preserved public APIs and owner data.

## verification
- Starting commit d8ef629 passed GitHub run 35586648410: 5,583 tests, 15 skips.
- Final cleanup Python suite: 5,574 tests pass, 6 environment-dependent skips (507.759 seconds).
  The first run found an obsolete control-count floor; the replacement measures 95% source coverage.
- JavaScript suite: 578 pass. Final CSS/census contracts pass after the mobile repairs.
- Current Files sorting/icons/breadcrumbs, populated Phase 7 operations/recovery, mobile transfer
  containment and hide/show behavior, and the finished-surface browser checks pass.
- Final port 8163 browser checks pass: 184 contrast surfaces / 2,755 text observations;
  92 resting-control surfaces / 1,518 controls; PWA offline/reconnect. No browser console errors.
- Ruff lint/format pass; canonical audit has 0 errors and 192 explained warnings, three fewer than before.
- Fresh screenshot review checked Files/Aide desktop/phone, light/dark Files, Andromeda and Settings.
- Evidence: docs/cleanup-2026-09-21.md. Local logs are in the temporary roots identified by
  /tmp/alles-cleanup-final-suite-current and /tmp/alles-cleanup-render-current.

## publication
Commit and publish the tested tree to dev-afterlife. GitHub's tests check on that exact commit is the
final acceptance gate; do not hand off a queued or failed run as a pass.

## retained limits
No live external-provider certification or new full-duplex voice integration. The product rework
remains a separate proposal. Active specialist modules, public APIs, migrations and recovery remain.

# Afterlife Phase 0 — execution checklist

- **Status:** delivered
- **Parent design:** [`design.md`](design.md)
- **Checkbox meaning here:** `[x]` means implemented with fresh evidence. It does not merely mean planned.

## Completed safety slices

- [x] Validate every restore archive member before touching live files.
  - Regression: a late zip-slip member returns 400 without changing the database or creating partial files.
- [x] Snapshot SQLite with the online backup API instead of copying `aide.db` after a best-effort checkpoint.
  - Regression: a committed WAL row survives while another connection holds an older read snapshot.
- [x] Bind fresh native starts to `127.0.0.1`.
  - `ALLES_HOST` is the explicit override. The container sets its internal bind deliberately, while the documented host publish stays loopback-only.
- [x] Refuse to kill an unknown process using Alles's port.
  - Start stops with a diagnosis; stop signals only a process whose working directory and `app.py` match this installation.
- [x] Store CLI PID/log files under `ALLES_DATA` when set.
- [x] Refuse `alles update` when the Git working tree has local changes.
- [x] Build recovery archive v1 with a strict manifest, exact file inventory, SHA-256 hashes,
  portable-path collision checks, archive limits, SQLite integrity, and migration compatibility.
- [x] Stream web backup/restore data through private temporary files instead of loading it into RAM.
- [x] Stage restores beside live data and never replace the running database from a web request.
  - Current manifest archives and legacy ZIPs both normalize into the same checked staging layout.
- [x] Apply restores only through the offline CLI state machine.
  - It re-hashes staging, boots/migrates it twice without network or background jobs, stops a verified
    server, holds the data-owner lock, journals both atomic renames, health-checks the installed copy,
    keeps the original data as rollback, and restores it automatically on failure.
  - Direct app starts refuse an unfinished restore; `alles restore recover` handles interrupted swaps.
- [x] Encrypt full downloads with streaming AES-256-GCM and a random recovery key.
  - The recovery key has a separate same-origin export and CLI restore accepts only the exported key.
  - A real isolated test restores from the encrypted container plus exported key, then proves the old
    installation is still present in the rollback snapshot.

## Verification evidence

- [x] Focused Phase 0 recovery/update checks pass in order-sensitive runs.
  - 79 backup, recovery, CLI, update, data-isolation, and no-original-install tests passed in
    25.575 seconds after the leaked `ALLES_DB` test environment was fixed.
  - 39 update/restore state-machine tests passed in 4.821 seconds.
- [x] Repository-wide baseline rechecked: 3,616 tests in 250.851 seconds.
  - Result: 24 failures, 84 errors, and 3 skipped.
  - This matches the earlier failure/error baseline. The remaining failures are in older Files, Vault,
    Gallery, and Booking paths; they are not in the new recovery checks.
- [x] Phase 0 Python lint, format, compile, JavaScript syntax, and scoped whitespace checks pass.
  - Scoped Ruff checks pass for every Phase 0 Python path; 27 new or isolated files pass Ruff format.
    The full dirty repository still has 196 older style findings and unrelated format/CRLF drift.
  - All 87 Node tests ran: 86 passed. The one existing Gallery non-array error-state mismatch is outside
    Phase 0; the Phase 0 subdomain/deep-link tests and all changed JavaScript syntax checks pass.
- [x] The independent disaster-recovery gate passes without the source installation.
  - A synthetic write was committed into SQLite WAL while an older reader stayed open. Alles created
    the manifest archive, encrypted it, and exported the recovery key to separate owner storage.
  - The test deleted the complete source installation, then used only the current clean code, encrypted
    backup repository, and exported key to stage, migrate, swap, boot, and re-boot a clean target.
  - Both committed rows, selected file hashes, full migration history, SQLite integrity, and foreign-key
    integrity survived. Fresh evidence: 1 end-to-end gate test passed in 7.525 seconds.

## Remaining recovery work

- [x] Build recovery archive v1 with a versioned manifest, path/size/hash inventory, archive limits, and SQLite/schema validation.
- [x] Extract and validate restores only in a staging directory; the web route must not perform a live in-place database replacement.
- [x] Add an offline CLI/supervisor swap with safety snapshot, stopped writers, health check, and automatic rollback.
- [x] Add authenticated backup encryption and a separately exportable/recoverable key.
- [x] Inventory every data class and configured local/remote root; record explicit inclusion and exclusion policy.
  - [`data-inventory.md`](data-inventory.md) now locks all 113 current mapped tables plus migration
    history, the exact 14 manifest root roles, Phase 7 local/WebDAV/S3 Storage Locations, managed
    service state, durable operations, offline copies, transient exclusions, and remote-service limits.
  - The inventory records the current external-Vault freeze/remap exception while external Files,
    Photos, Project, agent, and additional local Storage Location bytes remain excluded.
  - Fresh isolated evidence: the Phase 0 document/route lock plus backup/root regressions passed 42/42.
- [x] Add synthetic database fixtures for every supported schema and test restore → migrate twice → boot.
  - [`migration-support.md`](migration-support.md) defines the supported histories and exact fork map.
  - Frozen, secret-free SQL fixtures cover Beta 0.1.0, late legacy, and the Photos v13 fork.
  - Fresh matrix: 25 histories passed in 128.261 seconds: 2 released no-history schemas, canonical
    prefixes 1–18, and Photos-fork prefixes 9–13. Every case staged, booted/migrated twice, booted again,
    reached canonical history, preserved old rows/file hashes, and passed integrity/foreign-key checks.

## Remaining security and lifecycle work

- [x] Retire the prototype broad Passwords browser-extension flow and provide a safe fallback notice.
  - `/api/vault/match` revokes the exact pasted unlock token and returns `410 Gone` without resolving or
    extending it. Normal Passwords routes still work.
  - The old extension is now a notice-only MV3 shell with no permissions, host access, content script,
    background worker, page injection, or token storage. The Alles UI says to remove/reload it and use
    Passwords reveal/copy until a narrowly paired replacement exists.
  - Fresh evidence: 164 Vault/Passwords tests passed. Desktop 1280×800 and mobile 390×844 checks passed
    with reduced motion, keyboard focus, visible notice, no overflow, and zero console/page errors.
- [x] Stage and health-check updates with rollback instead of pulling directly into the live installation.
  - `alles update` fetches without changing live files, pins a fast-forward commit, rejects dependency
    changes, compiles a detached worktree, and refuses dirty trees, unknown processes, external
    `ALLES_DB`, unfinished maintenance, or data roots it cannot fully roll back.
  - It stops only the verified Alles process, holds the data-owner lock, creates an exact encrypted
    backup with writers stopped, boots the candidate twice on an isolated copy, and rechecks the tree,
    HEAD, and pinned upstream immediately before switching.
  - First use creates the recovery key before the snapshot, so the installed candidate and encrypted
    rollback backup keep the same key. Candidate `cli.py` is compiled and must pass a real rollback
    control-plane probe before any switch.
  - The candidate data directory is swapped through the existing restore journal. Normal startup stays
    blocked by a durable update marker except for the exact update token. Final-location and tracked-PID
    health checks must pass; the merged checkout is rechecked before data moves. Failure restores the
    old commit with `git reset --keep` and the exact stopped-data snapshot without deleting a late edit.
  - `alles update rollback` (or `recover`) resolves interrupted/applied updates. It refuses to reset if
    new edits, a different HEAD, or an unrelated restore appeared. Every partial rollback phase is
    resumable even when its marker or state-file cleanup was interrupted.
  - `alles update accept` verifies and keeps the encrypted backup, then removes the temporary full-copy
    stages, local restore rollback, journal, and one-click state before another update.
  - Fresh evidence includes first-key recovery, unrelated-restore rejection, concurrent-edit
    preservation, partial-rollback retry, missing-marker recovery, broken-candidate-CLI rejection,
    post-merge drift rejection, restart failure reporting, and accepted-snapshot cleanup.
- [x] Fix automation bookkeeping so success is recorded after the action and uncertain side effects are never retried blindly.
  - Migration 18 adds one durable, content-free claim per rule occurrence. Actions report `succeeded`,
    `failed`, or `uncertain`; interrupted claims become uncertain before background jobs start.
  - Rule state advances only after confirmed success. Manual tests return the real result, and Settings
    shows the latest failed or uncertain attempt instead of claiming it worked.
  - Push reminders, renewals, Days, calendar alerts, and proactive cards claim before delivery. Provider
    timeouts and 5xx responses are quarantined instead of retried. The browser acknowledges in-app
    reminder toasts separately, so reading `/due` no longer consumes them.
  - Scheduled mail uses `scheduled → sending → sent`; interrupted or ambiguous sends become visible as
    `uncertain`. Webhooks make one attempt, with timeouts/5xx recorded as uncertain and 4xx as rejected.
  - Shutdown now waits for the job loop and the startup photo database writer before releasing the
    single-instance lock.
  - Fresh focused evidence: 144 automation, push, reminder, proactive, mail, webhook, and notify tests
    passed. The 25-history recovery/migration matrix also passed with migration 18.
- [x] Add scoped compatibility/build metadata to backups and the running server.
  - Recovery manifests and `/api/system/build` expose only name, release version, build ID, recovery
    compatibility, and migration head. The running endpoint is read-only and follows the normal auth
    gate; it exposes no path, key, token, or private setting.
- [x] Define feature flags for incomplete Afterlife surfaces.
  - Six explicit flags cover the future shell, Home, Aide Projects, Andromeda, Jarvis, and Storage
    Locations. Every flag defaults off. `ALLES_AFTERLIFE_FEATURES` accepts only exact known names and
    rejects blanks, duplicates, and unknown values.
  - Fresh isolated evidence: 15 System/build/flag tests and 42 recovery integration tests passed.

## Remaining baseline work

- [x] Generate the current whole-system structure/trust map from code and tests.
  - `current-trust-map.md` records the browser, server, host-process, storage, model/search,
    connector, MCP, delivery, macOS, background-work, recovery, and update boundaries.
  - The refreshed 2026-07-19 map records 78 included routers, the locked 814-route digest and
    797/2/15 grouping, 16 canonical app subdomains plus aliases, all 23 registered jobs, scoped bearer
    auth, local/WebDAV/S3 Files roots, managed SearXNG, the Phase 8 Finance boundary, and current known
    limits.
  - A live-document regression derives the table, root, router, route, digest, and job facts from the
    implementation so future growth cannot silently leave the map stale.
- [x] Record route, subdomain, deep-link, desktop/mobile, Photos, PhotoKit, and research-failure baselines using throwaway `ALLES_DATA`.
  - Route/deep-link evidence: current Python checks lock 814 method/path pairs, the exact public
    surface, Phase 6 route preservation, and parser markers. Node checks lock the subdomain map and
    `notes`/`photos` aliases.
  - Browser evidence: `tests/pw_afterlife_phase0.py` passed 135/135 assertions against a blank
    throwaway server. All 21 current hosts rendered at 1280×800 and 390×844 without horizontal
    overflow, console errors, or server errors. Reduced motion, keyboard focus, failed-automation
    status, and uncertain-mail status also passed.
  - Photos/PhotoKit slice: 55 focused tests passed in 0.683 seconds with one expected macOS skip
    for the non-mac error contract. This locks the Photos header/sidebar alignment, native-helper and
    permission contracts, import UI/API, repeat sync, Live Photo pairing, and source migration.
  - Research evidence: 12 focused checks keep the failure result actionable and remove the old
    dead-end answer. The combined route/research run passed 15 tests; the Node map passed 3 more.
- [x] Inventory MCP, memory, personas, owner instructions, and Aide app capabilities without reading private content.
  - The code-only baseline is recorded in `current-platform-inventory.md`. It names fields and controls
    without opening live settings, databases, prompts, memories, MCP arguments, or vault content.
  - It locks the current 9 MCP, 10 memory, and 10 persona routes; 5 starter personas; 81 declared tool
    definitions; 82 registry tools including the `bash` alias; 36 app/browser tools; and 6 automation
    action names.
  - It also records the known gaps: Persona **None** still falls back to the default, incognito still
    reads/can write memory, 34 app tools have no typed scope, some state tools miss the mutation gate,
    and inbound MCP does not pass through interactive approval.
  - Fresh isolated evidence: 144 MCP, memory, user-model, persona, capability, policy, agent-tool, and
    Settings tests passed.
- [x] Record Andromeda latency on named reference hardware.
  - The shipped search input was measured on an 8 GB M1 MacBook Air with seven isolated public-query
    runs: 2.93 s median, 6.20 s nearest-rank p95, and 7/7 successful DuckDuckGo responses.
  - `search-latency-baseline.md` records exact runs, versions, isolation, and scope. It does not claim
    future AI-summary latency.

## Phase 0 gate

- [x] A clean release plus encrypted backup repository and exported recovery key restored to a
  throwaway location, migrated, booted, and preserved expected hashes/counts after the source
  installation was deleted.
- [x] Invalid archives, unknown processes, default network binding, failed updates, and uncertain side
  effects are covered by fail-safe regression tests.

## Phase 1 handoff — not part of the Phase 0 gate

- [x] Re-validate the encrypted local destination, then add WebDAV and S3 one at a time after encrypted
  connector storage exists and each target passes the same no-original-install recovery test.
  - This is Phase 1C in `design.md`. Phase 0 explicitly keeps the safe encrypted archive path instead
    of weakening recovery or storing remote credentials early.
  - Phase 1C completed independent local, WebDAV, and signed S3-compatible gates. Each remote gate
    deletes the source install and reconnects with credentials kept outside the backup.

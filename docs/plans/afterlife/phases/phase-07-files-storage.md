# Afterlife Phase 7 — Files and storage locations

- **Status:** delivered and freshly verified on 2026-07-18
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** [`phase-06-correction-pass.md`](phase-06-correction-pass.md) delivered and verified
- **Interface rule:** create, test, and get explicit approval for a standalone KOKUEN Files starter
  before materially changing the real Files interface.
- **Checkbox rule:** `[x]` means implemented and freshly tested with throwaway data.

## Goal

Give Files stable local and online location identity without risking the only copy. Local folders,
WebDAV, and S3-compatible storage share one understandable Files model. Offline availability is a
cache, never a backup. The existing specialist Photos experience remains intact.

## 7A — safe location identity

- [x] Add local, WebDAV, and S3-compatible Storage Locations with read-only or managed access.
- [x] Give the current Files root a stable default-local location record.
- [x] Use `location_id + normalized_path` for Files identity and add it to tags, stars, comments,
  versions, trash, shares, indexing, and operation history.
- [x] Keep legacy path columns and compatibility reads. Do not remove or rewrite owner metadata.
- [x] Audit row counts, normalized paths, hashes, tags, stars, versions, comments, trash, and shares
  before switching reads.
- [x] Make the migration idempotent and keep backup destinations separate from browsable locations.

**7A gate:** an upgraded synthetic database returns the same Files and metadata through legacy and new
lookups, and a second migration changes nothing.

## 7B — approved local Files experience

- [x] Build a standalone KOKUEN Files starter under `docs/mockups/` with fake local/online locations,
  three-pane browsing, multi-select, queued operations, offline, conflict, loading, partial, empty,
  and error states.
- [x] Test the starter on desktop and mobile with keyboard, reduced motion, custom controls, overflow,
  and console inspection.
- [x] Get explicit owner approval before changing the real Files interface.
- [x] After approval, add multiple local roots, read-only/managed permissions, background indexing,
  multi-select, queued copy/move/rename/delete/restore, undo, and restart-safe progress.

## 7C — WebDAV and offline availability

- [x] Store WebDAV credentials with the shared encrypted-secret boundary and detect server
  capabilities before enabling mutations.
- [x] Use ETags and conditional writes. Preserve both versions when the remote copy changed.
- [x] Resume transfers only when the server proves it supports the required range behavior.
- [x] Add explicit available-offline files and folders under the managed Alles data root.
- [x] Recover from disconnects, stale ETags, partial transfers, quota failure, cancellation, and
  restart without presenting cache bytes as backup.

## 7D — S3-compatible storage and Photos

- [x] Browse S3-compatible storage with ETags and version IDs when available.
- [x] Show non-atomic move/copy progress and verify the destination before source deletion.
- [x] Add Files to Photos without replacing the specialist Photos surface.
- [x] Preserve PhotoKit permission states, cancellation, the 500-item boundary, Hidden exclusion,
  source identity, repeat-import protection, restart recovery, and the non-macOS unavailable state.
- [x] Keep generated media under Aide to Creations.

## Interfaces

- [x] Add Storage Location list/create/update/remove/test APIs without returning credentials.
- [x] Add `location_id` to Files list/read/write/search/metadata calls while keeping the old default.
- [x] Add restart-safe operation queue, cancel, retry, and undo APIs.
- [x] Add offline-cache status and enable/disable APIs.
- [x] Keep old Files URLs working by resolving them through the default local location.

## Verification gate

Phase 7 is delivered only when synthetic old databases migrate without metadata drift; local,
WebDAV, S3, offline, conflict, network-loss, no-space, permission, cancel, crash, restart, undo, trash,
restore, backup, and recovery tests pass; and upload, move, delete, cache, or restore never removes the
only verified copy. Full Python, JavaScript, desktop/mobile browser, keyboard, reduced-motion, theme,
overflow, and console gates must use throwaway data.

- [x] Synthetic upgrade and second-run migration checks preserve identity and metadata.
- [x] Isolated local, WebDAV, S3, offline, conflict, failure, restart, undo, trash, and restore tests pass.
- [x] Destination verification protects the only verified copy during transfer and recovery tests.
- [x] The full Python and JavaScript suites pass after the final autoreview fixes.
- [x] Ruff lint and format checks pass after the final autoreview fixes.
- [x] Real desktop/mobile Files checks pass after the final autoreview fixes for keyboard, reduced motion, 200% zoom, themes, overflow,
  custom controls, and console errors.

## Current evidence

- The synthetic legacy migration preserves metadata and hashes, assigns the default local identity,
  records its audit counts, and makes no second-run changes.
- Legacy Files URLs and the new optional `location_id` calls pass the focused Files regression suite.
- Storage credentials use the shared encrypted-secret type and are never returned by the API.
- WebDAV and S3 browsing, verified writes, conditional conflicts, safe resume behavior, remote
  copy/move/delete/restore, and offline cache recovery pass focused transport tests. S3 deletion is
  conditional for unversioned objects and fails closed for objects with version IDs: creating a
  delete marker cannot be atomically tied to the verified version, so the source is preserved.
- The durable operation API exposes restart-safe state, bytes, retry/cancel/undo, and an honest
  `non_atomic` flag for remote transfers. A destination must match the source fingerprint before a move
  can delete its source.
- Files to Photos imports local or remote verified snapshots, keeps stable source identity, skips repeat
  imports, and cleans temporary remote copies without changing the specialist Photos interface.
- Background indexing is location-scoped, repeatable, bounded to readable text, and does not mutate
  read-only source files.
- The real Files screen now uses the approved multi-location KOKUEN workbench. It has no native
  product menus, checkboxes, or radios.
- On 2026-07-17, the direct Files safety backend gate passed 71 tests, including partial publication,
  S3 deletion races, undo metadata cleanup, terminal receipt cleanup, and cache-only offline reads.
  The real Files Playwright gate
  passed on desktop and mobile with keyboard, preview focus trapping and restoration, read-only
  restore protection, reduced motion, 200% text and zoom, light and dark themes, overflow, and console
  inspection. It also covered custom location choices, real upload and preview, selection, Files to
  Photos, rename, delete, restore, copy, undo, offline copies, access changes, and location removal.
- The complete JavaScript suite passes 352 tests. The complete Python suite passes 4,574 tests with
  four expected platform skips after the closing review fixes. Ruff lint, Ruff format,
  `git diff --check`, and the real Files browser gate pass. Every server and browser run uses
  throwaway `ALLES_DATA`.
- The final autoreview fixes safely resume operation-owned partial folders, clean each failed Photos
  import, release locations after terminal failed or cancelled operations, block read-only restore,
  make the preview a focus-managed modal, and describe mixed Photos imports accurately.
- The closing rerun also preserves metadata through undo-restore, permits safe first writes on empty
  WebDAV collections, releases side-effect-free cancelled operations, filters only exact internal
  transfer artifacts, refreshes derived Files views, keeps Starred search active across reloads, and
  traps focus through audio, video, and frame previews.
- The closing safety pass also keeps partial uploads hidden until atomic publication, rejects S3
  directory deletion when the live manifest changes, purges live metadata during undo, removes local
  operation receipts after terminal states, and keeps nested offline browsing, search, details, and
  previews strictly on cache-only endpoints after the source disappears.
- The final recovery pass adopts a failed move's verified survivor for later undo, restores local and
  remote Trash bytes if a concurrent replacement wins during restore or delete undo, resumes those
  safeguards after restart, and lets internal cleanup claim a disabled location without making that
  location browsable again.
- The closing ownership pass records a rename-stable identity for each published local file or tree,
  refuses to undo an atomically replaced same-byte destination, deletes exact verified S3 versions,
  preserves shared Trash version blobs, and keeps legacy rollback metadata recoverable. The isolated
  final autoreview reported no accepted or actionable findings.
- The final parity pass replaces the legacy `files / alles` breadcrumb with the approved Files-owned
  header, keeps real Home and Settings navigation, and preserves the location breadcrumb plus access
  and indexing status at desktop and mobile widths. The browser gate covers keyboard use, reduced
  motion, 200% zoom, both themes, overflow, and console state.
- Post-review ownership regressions keep the staged local publication identity through upload,
  same-root copy, crash recovery, delete quarantine, and move source removal; reject same-byte
  replacements; resume only exact owned S3 objects after versioning suspension; and reject S3
  `null` versions as exact ownership. The full regression gate also proved that OS process names
  containing filesystem surrogates are made safe before the System monitor returns UTF-8 JSON.
- Restarted copy undo and local delete now apply the same exact-ownership rule to an already existing
  quarantine. A same-byte race winner is restored to its public path before the operation refuses,
  and the shared helper applies that rule to sibling local publication-recovery paths.
- Local receipt construction translates publication/tree identity read failures into the storage
  error boundary, so a resumed move with an already removed source restores its armed survivor when
  the destination disappears or becomes unreadable during the receipt recheck.
- The standalone starter is
  [`../../../mockups/afterlife-navigation/files-storage.html`](../../../mockups/afterlife-navigation/files-storage.html).
  It still uses fake data only; the real Files screen now follows its approved direction.

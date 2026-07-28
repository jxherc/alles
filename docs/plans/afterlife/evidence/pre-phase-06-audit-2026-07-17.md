# pre-Phase-6 implementation audit

- **Date:** started 2026-07-17; implementation recheck completed 2026-07-18
- **Scope:** Afterlife Phases 0 through 5 against the current `dev-afterlife` implementation
- **Rule:** checked means the current requirement has a real implementation path and source, test, or
  rendered proof. Open means the current requirement is not proved. Superseded means a later accepted
  decision replaced the historical requirement; it is not counted as current or open work.
- **Owner data:** not used

## honest result

| Phase | Checklist rows audited | Current checked | Unchecked / open | Superseded |
|---|---:|---:|---:|---:|
| 0 - recovery gate and baseline | 33 | 33 | 0 | 0 |
| 1 - platform and security foundation | 33 | 32 | 0 | 1 |
| 2 - folder Projects and durable background core | 49 | 49 | 0 | 0 |
| 3 - product shell, Home, Aide Projects, and Settings | 38 | 36 | 0 | 2 |
| 4 - Aide and Andromeda | 56 | 47 | 0 | 9 |
| 5 - background Aide and channels | 29 | 29 | 0 | 0 |
| **total** | **238** | **226** | **0** | **12** |

The source phase files now contain 238 checked rows and 0 unchecked rows. Twelve of the checked rows
are retained only as historical delivery records and are explicitly classified below as superseded.
The earlier `238 verified / 0 open` conclusion was not supportable until the two real open requirements
below were implemented and documented.

## 2026-07-20 refresh

A fresh count against the six real source trackers found 33, 33, 49, 38, 56, and 29 checked rows for
Phases 0 through 5, with zero unchecked rows in every file. The classification remains 226 current,
zero open, and 12 explicitly superseded historical rows. The final isolated Python discovery passed
4,933 tests with five skips, and the live document guard still derives the current mapped-table,
root-role, route, digest, and job facts from the implementation. No row was promoted from a narrow
test or from planned Phase 8 behavior.

## document and implementation drift outside the totals

These findings do not add or remove a source checklist row, so they are recorded separately instead
of changing the 238-row arithmetic.

- The Phase 3 compatibility row used the label **All apps**, while the shipped rail action, dialog
  heading, and Home destination all say **apps**. The phase row now uses the real product label; its
  checked status did not depend on capitalization or the removed word.
- [`decision-aide-one-mode.md`](../decision-aide-one-mode.md) says there is no Compare destination or
  action. The current application still ships a working `compare-view`, Compare route, model picker,
  streaming comparison flow, and `/compare` navigation. The nine historical Phase 4 rows remain
  superseded by the accepted decision for checklist accounting, but the decision and real product
  are not currently aligned.
- [`phase-04-verification.md`](phase-04-verification.md) honestly records the older unavailable-runtime
  result and simulated rollback coverage. The newer dated Phase 4 plan records the supported-Docker
  live run completed on 2026-07-17, including explicit rollback. Current live-proof claims must cite
  that newer record rather than silently treating the older evidence page as current.

## unchecked / open requirements

None. All 226 current rows have implementation evidence. The 12 remaining checked source rows are
historical delivery records explicitly classified as superseded below.

## requirements closed after the audit started

- [x] **Phase 0 current data/root inventory.** Refreshed again after Phase 8 from runtime model/root
  enumeration. It now records all 113 mapped tables, the 14 manifest root roles, Phase 7 Storage
  Locations and durable/offline state, managed SearXNG and Actual state, external-Vault capture/remap,
  and exact byte inclusion/exclusion policy.
- [x] **Phase 0 current whole-system trust map.** Refreshed on 2026-07-18 with 76 included routers,
  795 locked method/path pairs at the pre-Phase-8 checkpoint. The current post-Phase-8 map records 78
  routers and 814 method/path pairs with the new Finance routes, the current digest and grouping, 23
  jobs, scoped bearer auth, local/WebDAV/S3 Files boundaries, managed SearXNG, and managed Actual. The
  document lock derives these current values from the implementation.
- [x] **Phase 3 Home customization in Settings.** The owner approved the standalone KOKUEN starter.
  The real Settings Home pane now controls section order and visibility, density, and shortcut order
  and visibility through custom accessible controls. Needs you cannot be hidden. Focused backend,
  JavaScript, existing Home, and new desktop/mobile browser gates prove immediate updates, restart
  persistence, reset, error recovery, keyboard use, reduced motion, 200% zoom, and responsive layout.
- [x] **Phase 5 current delivered-behavior documentation.** `specifications.md`, the phase index, and
  current-stage status now match the delivered managed SearXNG lifecycle, independent scoped bearer
  tokens, and Settings-based Home customization.

## superseded historical requirements

These rows remain checked only as records of what an earlier phase delivered. They do not describe
the accepted current product.

- **Phase 1 (1):** the three visible model roles row. The accepted one-mode decision removes Jarvis as
  an in-app model role; Settings currently exposes Aide and Andromeda. Compatibility backend remnants
  remain and should not be mistaken for current UI proof.
- **Phase 3 (2):** separate Aide-to-Jarvis model default and the Automatic tools / Answer only choice.
  The old Cowork/Jarvis alias row remains a current compatibility obligation; only its historical
  “with Jarvis selected” wording was replaced by the one-mode decision.
- **Phase 4 (9):** Chat/Jarvis selector; Answer only override; selector-state preservation; Compare as
  an Aide action; Keep here / Run with Jarvis; separate Jarvis task creation; opening that task in the
  Aide sidebar; Run deep research with Jarvis; and rendering the conclusion before tool history.

The accepted [`decision-aide-one-mode.md`](../decision-aide-one-mode.md) replaces those requirements
with one Aide mode, same-conversation background work, and no Jarvis or Compare product mode. Some
compatibility route/model remnants still exist; their presence does not make the superseded controls
current requirements.

## current implementation proof

- Phase 0 route compatibility currently locks 814 method/path pairs. Its browser baseline covers the
  21-host Phase 0 compatibility slice, responsive widths, keyboard focus, reduced motion, overflow,
  and console errors; it is not proof of every current canonical and legacy host entry.
- Phase 1 scoped bearer-token API and desktop/mobile UI checks cover independent bearer auth and
  per-token scopes.
- Phase 2 has no non-current checklist row in the source/implementation audit.
- Current Home/Apps, one-mode Aide, Andromeda, background/scheduled Aide, and Discord settings have
  focused source, unit, JavaScript, and browser coverage.
- The dated Phase 4 record reports a supported-Docker live run for install, search, health, limits,
  restart, failed-pull and failed-health rollback, update, explicit rollback, and uninstall while
  retaining data. The Phase 6 correction-pass record proves rollback paths with focused tests but
  explicitly does not claim a live explicit-rollback run.
- Final Phase 7 verification now records 271 focused backend tests, 399 broader backend module tests,
  180 final local file-operation/storage/S3 regression tests, 4,574 full Python tests with four
  expected platform skips, 352 JavaScript tests, Ruff lint and format, `git diff --check`, and the
  isolated desktop/mobile Files browser gate. The safety-isolated final autoreview was clean with no
  accepted or actionable findings. These gates verify implemented behavior but cannot convert the
  implementation gaps into checked requirements without the focused proof recorded above.

## boundary

This audit classifies all 238 checklist rows present in the current Phase 0-5 files against the
current implementation. It does
not silently rewrite accepted decisions, count a superseded UI as missing work, treat stale documents
as proof, or turn planned Phase 8 behavior into shipped behavior.

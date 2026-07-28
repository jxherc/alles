# Afterlife Phase 10 - localization and release hardening

- **Status:** delivered and verified 2026-07-21
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** [`phase-09-distribution-browser-access.md`](phase-09-distribution-browser-access.md) delivered and verified
- **Design review:** [`../phase-10-design-review.md`](../phase-10-design-review.md)
- **Baseline:** [`../evidence/phase-10-baseline-2026-07-21.md`](../evidence/phase-10-baseline-2026-07-21.md)
- **Real Settings UI QA:** [`../evidence/phase-10-settings-ui-qa-2026-07-21.md`](../evidence/phase-10-settings-ui-qa-2026-07-21.md)
- **Localization delivery:** [`../evidence/phase-10-localization-delivery-2026-07-21.md`](../evidence/phase-10-localization-delivery-2026-07-21.md)
- **Release hardening:** [`../evidence/phase-10-release-hardening-2026-07-21.md`](../evidence/phase-10-release-hardening-2026-07-21.md)
- **Aide and architecture:** [`../evidence/phase-10-aide-architecture-2026-07-21.md`](../evidence/phase-10-aide-architecture-2026-07-21.md)
- **Final audit:** [`../evidence/phase-10-final-audit-2026-07-21.md`](../evidence/phase-10-final-audit-2026-07-21.md)
- **Checkbox rule:** `[x]` means implemented and freshly verified. `[ ]` means open.

## Goal

Ship eight honestly reviewed interface languages, locale-aware deterministic Task and Calendar input,
offline RTL/CJK/Arabic support, complete credits and license artifacts, and current release-hardening
evidence without changing owner data or presenting fallbacks as finished translations.

## 10A - inventory and contracts

- [x] Audit current localization, locale formatting, parser, README, credit, vendored asset, and notice
  foundations against the real worktree.
- [x] Record the eight canonical language identifiers and separate language from region, timezone,
  clock, week-start, and currency choices.
- [x] Add machine-checked catalog metadata, key/placeholder/plural parity, and review-state contracts.
- [x] Add a deterministic credits manifest schema and coverage audit for runtime and packaged assets.
- [x] Build and browser-verify the standalone KOKUEN Settings starter at
  [`../../../mockups/afterlife-release/localization-credits.html`](../../../mockups/afterlife-release/localization-credits.html).
- [x] Obtain explicit owner approval of the standalone starter before real language/Credits UI changes.

## 10B - localization runtime and formatting

- [x] Load reviewed local catalogs before localized UI renders and retain safe English fallback.
- [x] Move static markup and JavaScript-rendered interface copy to stable translation keys without
  translating owner or third-party content.
- [x] Route dates, times, numbers, currencies, lists, relative time, and plurals through shared locale
  helpers; remove hard-coded `en-US` from locale-sensitive product output.
- [x] Persist and apply language, region, timezone, clock, week start, and currency independently.
- [x] Update `lang`/`dir` safely on switch and preserve current pane, focus, and recoverable state.

## 10C - eight reviewed languages and local input

- [x] Complete and review English as the canonical catalog.
- [x] Complete and review French.
- [x] Complete and review Spanish.
- [x] Complete and review Simplified Chinese (`zh-Hans`).
- [x] Complete and review Traditional Chinese (`zh-Hant`).
- [x] Complete and review Japanese.
- [x] Complete and review Korean.
- [x] Complete and review Arabic, including plurals and mixed-direction content.
- [x] Add deterministic localized Task quick-add for all eight languages.
- [x] Add deterministic localized Calendar quick-add for all eight languages.
- [x] Publish translated READMEs with the canonical source revision and honest review state.

## 10D - offline typography and rendered interface

- [x] Remove required remote fonts and runtime UI CDN dependencies, or vendor reviewed versions with
  complete licenses and offline fallbacks.
- [x] Verify font coverage, shaping, line breaking, truncation, numeric/path isolation, and input caret
  behavior for Arabic, Chinese, Japanese, and Korean.
- [x] Verify each language at desktop and 390 x 844, 200 percent zoom, keyboard-only, both themes,
  reduced motion, offline mode, focus return, overflow, and clean console.
- [x] Verify the approved real custom language selector and Credits surface with no native choice
  controls.

## 10E - credits, notices, and release artifacts

- [x] Inventory direct and bundled Python/JavaScript dependencies, vendored assets, fonts, models,
  datasets, skills, managed companions, and adapted code with exact versions and sources.
- [x] Generate readable `ACKNOWLEDGMENTS.md`, `THIRD_PARTY_NOTICES.md`, and a complete `licenses/`
  bundle from the manifest.
- [x] Add a manifest-driven Settings Credits view with local license text and source links.
- [x] Fail release checks when a shipped item lacks a notice, license value, or required license text.
- [x] Prove native and container artifacts contain the exact generated notice set.

## 10F - release hardening and reconciliation

- [x] Run the supported macOS/Linux compatibility and clean-install/upgrade/rollback/uninstall matrix.
- [x] Run the accessibility, keyboard, zoom, theme, reduced-motion, offline, and partial/error matrix.
- [x] Define and pass representative server/browser performance budgets without hiding slow paths.
- [x] Run security, privacy, secret-leak, origin, permission, dependency, and data-boundary sweeps.
- [x] Run backup/restore and interrupted-recovery proof across current local, WebDAV, S3, Files,
  external Vault, Actual, and managed-service state.
- [x] Audit every Aide capability row and record a working test or explicit intentional exclusion.
- [x] Reconcile `specifications.md` structure/trust maps with current routes, services, processes,
  stores, jobs, connectors, and managed companions.
- [x] Update shipped behavior documentation only where the implementation and fresh evidence agree.

## Final gate

- [x] Focused localization, parser, credits, packaging, and hardening tests pass with throwaway data.
- [x] Full Python and JavaScript suites pass.
- [x] Repository-wide Ruff lint/format and diff integrity pass.
- [x] The real Git index is empty; no commit or push is made.
- [x] A final requirement-by-requirement audit records honest checked and unchecked status.

**Final audit:** all 44 delivery rows are checked against current-worktree evidence. The internally
reviewed eight-language core-flow contract, localized parsers and READMEs, offline rendered matrix,
432-entry credit inventory, 465-file release notice set, native/container proof, hardening matrices,
5,021-test Python suite, 432-test JavaScript suite, and final lint/format/diff/index checks pass. The
evidence keeps physical-Linux, live-owner-remote, native-speaker-review, and explicit translation-scope
limits visible. No autoreview, commit, or push was performed.

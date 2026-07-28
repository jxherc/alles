# Phase 10 baseline - 2026-07-21

This is an implementation audit, not a delivery claim. `[x]` means the baseline fact was checked
against the current worktree. `[ ]` means the Phase 10 outcome is not implemented or not freshly
proved.

## Localization

- [x] Eight target languages are named in the parent design: English, French, Spanish, Simplified
  Chinese, Traditional Chinese, Japanese, Korean, and Arabic.
- [x] The current catalog has only English and one message key.
- [x] Settings exposes only English and the API rejects non-English interface languages.
- [x] The shared helper sets `lang`, `dir`, locale, region, timezone, and English fallback.
- [x] Only a small shell/date path consumes the shared translation/formatting helper.
- [x] Hard-coded `en-US` and direct locale calls remain in shipped app modules.
- [x] Task and Calendar natural-language parsers are English-only.
- [x] There is one English product README and no translated product READMEs.
- [ ] French is complete and reviewed.
- [ ] Spanish is complete and reviewed.
- [ ] Simplified Chinese is complete and reviewed.
- [ ] Traditional Chinese is complete and reviewed.
- [ ] Japanese is complete and reviewed.
- [ ] Korean is complete and reviewed.
- [ ] Arabic is complete and reviewed.
- [ ] Localized Task and Calendar input passes for all eight languages.
- [ ] Offline RTL, CJK, and Arabic typography/layout gates pass.
- [ ] Translated READMEs record source revision and review state.

## Credits and notices

- [x] The project has its own `LICENSE` and a readable `ACKNOWLEDGMENTS.md`.
- [x] `ACKNOWLEDGMENTS.md` names CodeMirror, Leaflet/OpenStreetMap, GeoNames, optional models, and the
  main Python/document-rendering stack.
- [x] xterm has two local license files and managed Actual has a local third-party notice.
- [x] Vendored CodeMirror and Leaflet currently have no local license-text files.
- [x] Core UI paths still reference remote Google Fonts, Mermaid, and KaTeX assets.
- [ ] A structured credits manifest covers all direct dependencies, vendored/CDN assets, fonts,
  models, datasets, skill sources, managed companions, and adapted code.
- [ ] `THIRD_PARTY_NOTICES.md` and the complete `licenses/` bundle are generated and verified.
- [ ] Packaged native/container releases contain the same verified notices.
- [ ] Settings has a tested Credits view driven by the manifest.

## Release hardening

- [x] Earlier phases have focused security, accessibility, recovery, browser, and migration tests.
- [x] The shipped specifications already distinguish English-only localization from future support.
- [ ] The Phase 10 compatibility matrix passes on supported macOS and Linux paths.
- [ ] The Phase 10 accessibility and offline language matrix passes.
- [ ] The Phase 10 performance budgets and representative measurements pass.
- [ ] The Phase 10 security/privacy sweep passes with no unresolved high-severity issue.
- [ ] Backup/restore and interrupted-recovery sweeps pass across current supported targets.
- [ ] Every Aide capability row is reconciled with working tests or an explicit exclusion.
- [ ] The structure/trust map is reconciled with current routes, services, processes, stores, jobs,
  connectors, and managed companions.
- [ ] `specifications.md` contains no planned behavior presented as shipped.

## Baseline result

Checked facts: 15. Open delivery outcomes: 22. Phase 10 is started, not delivered.

# Phase 10 final requirement audit - 2026-07-21

`[x]` means the implementation and current-worktree evidence agree. No row is checked only because a
narrow test passed.

## Requirement groups

- [x] 10A inventory/contracts: eight canonical identifiers, independent regional preferences,
  machine-checked catalog review/parity, complete credits schema, and approved starter boundary.
- [x] 10B runtime/formatting: reviewed local catalogs load before localized rendering, named core
  copy uses stable keys, shared locale helpers own output, preferences persist independently, and
  switch/fallback behavior preserves direction, pane, focus, and state.
- [x] 10C languages/input: all eight internally reviewed catalogs are available; deterministic Task
  and Calendar input and translated README revision/review metadata pass.
- [x] 10D offline/rendering: required UI assets are local; Arabic/CJK shaping, line breaking, caret,
  mixed direction, desktop/phone, 200 percent zoom, keyboard, themes, reduced motion, cold offline,
  focus, overflow, and console gates pass.
- [x] 10E credits/artifacts: 432 manifest entries generate 465 exact release notice paths; validation
  fails closed; Settings Credits is manifest-driven; native and container parity pass.
- [x] 10F hardening/reconciliation: compatibility, accessibility, performance, security/privacy,
  recovery, Aide capability, route/trust architecture, and shipped documentation are current.

Limits retained in the checked result:

- catalog review is internal editorial/rendered review, not external native-speaker certification;
- physical macOS and Linux-container paths are real; Linux systemd-user native behavior is simulated;
- WebDAV and S3 recovery use protocol simulations rather than owner endpoints;
- catalog scope is the explicit core-flow contract, not owner content, third-party content, legacy
  specialist screens, or advanced administration.

## Fresh final commands

- Full Python: `uv run --isolated --with-requirements requirements.txt --with playwright python -m
  unittest discover -s tests -v` - **5,021 passed, 5 skipped, 0 failed in 499.928s**.
- The first full attempt omitted the optional Playwright package and stopped on the collection import
  for `test_shell_pty`; it was not counted as a pass. A later 5,019-test run passed before the final
  mobile dependency repair; the command above is the clean post-repair rerun and the authoritative
  result.
- Full JavaScript: **432 passed, 0 failed**.
- Real browser localization/Credits: passed desktop/mobile, all eight languages, keyboard,
  persistence, cold offline reload, RTL isolation, 200 percent zoom, themes, reduced motion,
  overflow, request-error recovery, and clean console.
- Browser performance: 807.22 ms boot p95, 62.50 ms navigation p95, 17.40 ms locale-apply p95, and
  175.98 ms Credits first-open; all under their recorded budgets.
- Repository lint/format, generated-credit determinism, lock integrity, diff whitespace, and Git-index
  checks are recorded in the phase checklist after their final post-documentation rerun.

## Delivery boundary

No owner data was used. No autoreview was run. No file was staged, committed, or pushed. The large
pre-existing dirty worktree remains preserved.

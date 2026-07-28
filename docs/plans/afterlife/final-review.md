# Afterlife final review and handoff

- **Status:** Phase 11 complete 2026-07-21; approved remaining-gap implementation completed 2026-07-22
- **Worktree:** `dev-afterlife` in `afterlife-check`, revision baseline `d0098f9`
- **Execution plan:** [`phases/phase-11-post-development-review-handoff.md`](phases/phase-11-post-development-review-handoff.md)
- **Result:** 40 of 41 original brainstorm requests satisfied; 1 honestly open; 27 of 27
  final-acceptance rows verified.
- **Evidence rule:** `[x]` means current implementation and fresh Phase 11 evidence agree. `[ ]`
  means a real gap, accepted limitation, or owner-approval boundary remains.
- **Safety boundary:** synthetic or throwaway data only; no owner database, vault, files,
  connectors, credentials, or Photos library; no autoreview, commit, or push.

The authoritative brainstorm contains 41 top-level requests. Its original `[x]` marks mean the
requests were acknowledged and mapped into the plan. They are not delivery evidence. Each row below
was checked again against the current implementation and tests.

## Original brainstorm reconciliation

### Workflow and bugs

1. [x] **Staged workflow:** the Afterlife design, per-phase design records, implementation records,
   detailed Phase 11 review, focused regressions, full suites, real browser checks, and this handoff
   preserve the requested brainstorm, design review, development, review, test, and end-to-end order.
2. [x] **Host OS and Server:** `core/server_config.py` and `services/sysmon.py` derive the host from
   the server, not browser identity. `tests/test_server_config.py`, the physical macOS native gate,
   and the real Linux container gate passed.
3. [x] **Universal models and custom endpoints:** `services/model_catalog.py`,
   `services/model_resolver.py`, model routes, and Settings support role defaults plus global and
   endpoint refresh. Catalog/resolver tests cover failure retention and removed defaults.
4. [x] **Research recovery:** Andromeda regular results, optional cited overview, bounded source
   failure detail, continuation, and save actions replace the old dead end. Python, JavaScript, and
   rendered Andromeda gates passed.
5. [x] **Ask Docs replacement:** Docs sends a private, hash-bound note scope to normal Aide through a
   one-time context handoff. `tests/test_aide_document_scope.py`, SSO context tests, and Docs browser
   routing passed.
6. [x] **Aide scroll ownership:** `static/js/scrollfollow.js` follows only near the bottom and does not
   recapture while the owner reads, types, or selects. JavaScript scroll-follow regressions passed.
7. [x] **Completed steps:** Aide reloads completed steps collapsed, failed steps open, and preserves
   the reopen control and durable source/revert state. `aide_afterlife_shell.test.mjs` passed.
8. [x] **Photos alignment:** Gallery/Photos routing, Files-to-Photos handoff, source identity, and
   current labels agree. Phase 7 Files and Phase 8 specialist browser gates passed.
9. [ ] **Token and incognito reference icons:** incognito state and privacy behavior are fixed and
   tested, but the token glyph remains behind the recorded owner visual-approval boundary. This row
   is not claimed complete without that approval.
10. [x] **Personas:** None/default behavior, explicit persona choice, custom persona preservation,
    starter content, and persona knowledge files are covered by persona API/docs tests and Aide model
    regressions.
11. [x] **Model discovery:** global and per-endpoint refresh preserve the last good catalog, serialize
    writes, remove stale endpoint models from pickers, and mark broken defaults instead of silently
    switching providers.

### Functions

12. [x] **Approved design starters:** material app reworks retain their recorded standalone KOKUEN
    starter and approval chain. Phase 11 used the owner's explicit no-mock waiver and made only
    targeted privacy, copy, password-policy, packaging, and test repairs.
13. [x] **Whole-system map:** `specifications.md` and the Phase 0 trust/data records map current
    routes, storage, processes, network boundaries, data ownership, migrations, and compatibility.
14. [x] **Packaging and legal artifacts:** native and container packaging include runtime metadata,
    complete notices/licenses, translated READMEs, migrations, and health/build evidence. The release
    packaging tests, credits generator, macOS gate, and Linux image gate passed.
15. [x] **Discord:** Jarvis exists only as the revocable owner-scoped Discord connection through
    `services/jarvis_discord.py`; OpenClaw is acknowledged as inspiration, not a dependency.
16. [x] **Background Aide:** durable work is normal Aide behavior, survives navigation/restart, stays
    in the same session, and keeps approval boundaries. Background and scheduled browser gates passed.
17. [x] **Cron/heartbeat:** scheduler, heartbeat, durable runs, retry, outbox, and automation records
    work without OpenClaw. Jarvis scheduler/outbox and automatic-backup tests passed.
18. [x] **MCP:** owner-managed servers can be added, tested, refreshed, disabled, revoked, and granted
    to exact Aide/Project/Workflow scopes. MCP API/server/credential migration and malicious-output
    tests passed.
19. [x] **Memory:** remember, forget, review, accept, edit, export, clear, Project scope, owner
    instructions, provenance, off/review/auto policy, and incognito non-persistence are implemented
    and covered by memory policy/store/extraction and JavaScript privacy tests.
20. [x] **Daily-app Aide coverage:** the capability map implements or explicitly excludes read,
    action, and customization access for every daily product area; risk and unavailable-tool states
    stay visible.
21. [x] **Plan List and Board:** the Phase 8 Plan workbench composes Calendar, Tasks, and Reminders over
    the same task records, with List/Board views and stable capture/error handling.
22. [x] **PhotoKit:** the native signed helper, authorization states, resource export, background job,
    source identity, and Gallery action remain implemented. The physical macOS status path plus mocked
    permission/import browser gate passed without reading the owner Photos library.
23. [x] **Acknowledgements:** `ACKNOWLEDGMENTS.md`, `THIRD_PARTY_NOTICES.md`, `credits/manifest.json`,
    `licenses/`, and the release notice set cover inspirations and shipped dependencies. Generator
    validation passed.
24. [x] **Specialist consolidation:** Plan, Inbox, Library, Health, and Finance own the approved
    workbenches; compatibility routes preserve old identifiers and subsections. Phase 8 real browser
    coverage passed in both themes and mobile/desktop.
25. [x] **Docs/Journal/Obsidian:** byte-preserving Markdown, conflict detection, preview/edit, safe
    drafts, vault moves, Journal migration, and optional Obsidian setup are covered by preservation,
    migration, vault, and browser tests.
26. [x] **Finance/Actual:** Actual is the gated canonical ledger; imports preserve source currency,
    require review for ambiguity, remain idempotent, and avoid two writable ledgers. The real pinned
    Actual install/migrate/write/backup/restore/fresh-readback gate passed.
27. [ ] **Proxy companion:** pinned preparation, loopback-only first-admin setup, encrypted API token,
    proxy/certificate status, typed host creation, listener preflight, and rollback pass automated tests.
    A disposable-network activation with real test domains is still unchecked.
28. [ ] **AdGuard companion:** pinned preparation, sealed credentials, native statistics/filtering/
    rewrite APIs, TCP/UDP preflight, and rollback pass automated tests. A disposable-network DNS
    activation and recovery test is still unchecked.
29. [x] **Settings placement:** Home customization, pinned apps, appearance, model roles, endpoint
    catalogs, language, and regional behavior live in Settings. Real Home/Settings browser gates pass.
30. [x] **Native CLI and Obsidian:** supported native installation creates the `alles` command,
    resumable first-run setup, launchd/systemd-user ownership, optional Obsidian integration, update,
    rollback, and uninstall-keep-data behavior. The physical macOS gate passed.
31. [x] **Eight languages and READMEs:** all eight named catalogs, locale helpers, deterministic input,
    cold-offline loading, RTL isolation, and translated READMEs ship with an honest internal-review
    state. This is not external native-speaker certification.
32. [x] **Scheduled News to Home/Jarvis:** Aide Scheduled now owns one first-class News workflow with
    tested RSS/Atom sources, disabled-by-default scheduling, automatic timezone, conditional polling,
    per-source backoff, dedupe/clustering, bounded summary fallback, substantive Home briefs, durable
    optional Jarvis delivery, and explicit-only Library save. API, migration, service, JavaScript, and
    real rendered workflow regressions passed.
33. [x] **Andromeda Overview:** normal search can show a cited overview above ordinary results; `!ai`
    keeps ordinary results only; partial/local failure preserves links without silent remote fallback.
    Perplexica is credited as inspiration only.
34. [x] **Passwords extension:** pairing, approval, exact-site matching, short-lived release, restart
    lock, frame/lookalike rejection, revocation, and no general Vault token are implemented. The real
    unpacked Manifest V3 extension gate passed.
35. [x] **Projects/history:** Projects select a folder, group Aide threads, bind terminal/tools to the
    visible working root, and keep General free of an implicit repo or write root.
36. [x] **One Aide mode:** Aide has one normal tool-capable behavior with saved automatic defaults and
    visible per-conversation override; Jarvis remains Discord-only. No Chat/Agent/Jarvis app mode is
    shipped.
37. [x] **Permitted provider sign-in only:** unsupported or provider-forbidden consumer OAuth is an
    explicit non-goal. Only permitted credential flows appear, and Settings warns about provider
    quota/credits before use. The accepted decision supersedes the original broad OAuth wording.
38. [x] **Owner choices in Aide:** durable work records explicit waiting/choice states, preserves the
    decision context, and resumes only after the owner answers. Delegated-action and Jarvis record
    tests passed.
39. [x] **Files roots, previews, scopes, and Vault:** approved local/WebDAV/S3 locations, scoped
    operations, safe previews, durable transfers, explicit Vault placement/move, and recovery are
    implemented and passed the real Phase 7 browser gate.
40. [x] **macOS/Linux focus:** native behavior and docs focus on macOS/Linux; Windows is not presented
    as equal support. Physical macOS and Linux-container paths passed.
41. [x] **Files resilience:** location metadata, offline copies, sync state, backup destinations,
    version/identity checks, interruption recovery, and owner-visible operations keep sync, offline,
    and backup distinct.

## Final acceptance reconciliation

1. [x] Home remains useful with zero configured model.
2. [x] Aide has one interface and one tool-capable behavior; Jarvis is not an in-app mode.
3. [x] Aide uses approved tools when useful, keeps simple answers simple, and never bypasses mutation
   approval except the explicitly selected Full access mode.
4. [x] Thinking/steps precede the answer, completed detail reopens, and scroll ownership is preserved.
5. [x] Memory review/edit/export/clear, Project scope, owner instructions, and incognito boundaries work.
6. [x] Every daily product area has implemented or explicitly excluded Aide coverage.
7. [x] Normal Andromeda search shows cited overview plus results; `!ai` omits only the overview.
8. [x] Version-sensitive answers prefer current official evidence and expose checked/source state.
9. [x] Research failure offers bounded cause, regular results, retry/continuation, and no dead end.
10. [x] Supported local overview failure preserves results and does not silently call remote models.
11. [x] Background Aide survives restarts and cannot perform an unapproved mutation.
12. [x] Jarvis is only the owner-scoped revocable Discord bot.
13. [x] MCP servers are testable, refreshable, disableable, revocable, and exactly granted.
14. [x] Projects bind one visible working folder and use normal permissions outside it.
15. [x] Markdown survives visual editing and concurrent Obsidian changes.
16. [x] Vault placement is explicit; failed moves leave the original usable.
17. [x] Files browses approved local/online locations without confusing sync and backup.
18. [x] PhotoKit and Photos alignment survive the Files redesign.
19. [x] Finance uses the approved Actual core, preserves currency, and imports idempotently.
20. [x] Server manages only Alles-owned services and recovers failed updates.
21. [ ] Server uses host OS and companion activation prevents silent network mutation; real isolated
    DNS/proxy activation and recovery evidence is still outstanding.
22. [x] Model catalogs refresh globally/per endpoint and retain honest broken/removed state.
23. [x] Provider account login is limited to permitted flows with quota/credits warning.
24. [x] A verified encrypted backup restores the selected installation.
25. [x] The browser extension receives neither a general Vault token nor permanent all-site access.
26. [x] Supported languages, notices, old routes, mobile, keyboard, zoom, themes, and reduced motion pass.
27. [x] `specifications.md` and this record contain the required structure, trust, review, test, and
   end-to-end evidence.

## Detailed review findings

| ID | Severity / confidence | Finding | Disposition and regression proof |
|---|---|---|---|
| F11-01 | high / high | Docker context could send `.env`, agent state, or local instruction files to the daemon. | Fixed in `.dockerignore`; packaging regression asserts the exclusions; image rebuild passed. |
| F11-02 | medium / high | Sandboxed HTML email still allowed remote tracking images. | CSP now precedes untrusted markup and permits only `data:`/`cid:` images; UI states the block; JS privacy regression passed. |
| F11-03 | medium / high | New owner and Vault passwords still allowed four-character setup. | New/change/setup floors are 12 characters while existing weak verifiers remain unlockable for migration; 69 auth and 301 Vault-family tests passed. |
| F11-04 | medium / high | Journal could create/change a one-character access passcode. | New/change floor is 12; existing unlock remains compatible; all 86 Journal-family tests passed. |
| F11-05 | medium / high | Full access copy implied secret confinement although an unsandboxed shell has normal host access. | UI/runtime note now names the unrestricted shell boundary and credential-store rule; focused Python/JS tests passed. |
| F11-06 | low / high | Browser gates retained retired dialog selectors, an old Reminders weight, removed Calendar handoff, and favicon assumptions. | Gates now target the current accessible dialog/routes/rendering; KOKUEN, Aide, Andromeda, and PhotoKit gates passed. |

No unresolved critical or high-severity finding remains.

### Security, privacy, migration, and dependency audit

- `pip-audit`: no known vulnerabilities in `requirements.txt`.
- `npm audit --omit=dev --audit-level=low`: zero vulnerabilities in both
  `integrations/actual` and `mobile`.
- Bandit over `core`, `routes`, `services`, `app.py`, and `cli.py`: 0 high, 26 medium,
  272 low. Every medium was inspected. They are deliberate bind-policy branches, HTTP(S)-validated
  fetches, or SQL assembled only from fixed schema/migration identifiers. None is an exploitable
  user-controlled sink.
- Bounded sink search found no `shell=True`, `os.system`, dynamic Python `eval`/`exec`, unsafe pickle,
  unsafe YAML load, or unchecked archive extraction path.
- Tracked-secret patterns found only synthetic test values and AWS's published S3 signing vector.
  No tracked runtime `.env`, database, key, vault, upload, or owner-data artifact was found.
- Migrations 33 through 41 were reviewed. Migration 33 count-audits its table rebuild before legacy
  drop; 34-41 are additive/idempotent; migration 37 removes invalid evidence instead of inventing it.
  Canonical and photo-fork prefix restore/migrate-twice/boot coverage passed in the full suite.
- Backup/restore, Files operations, Actual cutover, native update/rollback, and uninstall paths keep
  original data until verified replacement and expose interruption/recovery state.

## Lifecycle and end-to-end evidence

| Surface | Evidence | Result / boundary |
|---|---|---|
| Full regression | 5,043 Python tests; 444 JavaScript tests | pass; 5 documented Python skips, 0 failures |
| Lifecycle/recovery focus | 390 install/update/backup/restore/migration/Actual/WebDAV/S3 tests | pass; one opt-in Actual live test excluded here and run separately |
| Actual | official pinned runtime install, migrate, write, backup, restore, restart, fresh-client readback | pass in 39.981s; runtime process cleaned |
| macOS native | real current-host install/launchd/uninstall-keep-data gate | pass with throwaway Application Support root |
| Linux | prior Phase 11 real Docker build/run on loopback through migration head 40; migration 41 has isolated migrate-twice coverage | pass within stated boundary; container removed, local test image retained |
| Files Phase 7 | real browser gate on macOS temp root | pass |
| Specialist Phase 8 | desktop/mobile, both themes, keyboard, cutover rollback, partial/error states | pass |
| Phase 9 setup/Passwords | real setup and Vault gate plus unpacked Chrome extension lifecycle | pass |
| Phase 10 localization/Credits | eight languages, desktop/mobile, RTL, offline, zoom, themes, keyboard | pass |
| Plan board | real existing-task create, filter, atomic drag reorder, explicit movement, details, completion history, desktop/phone/200% zoom, keyboard | pass; isolated Task records, clean console |
| Scheduled News | real enable/configure, automatic timezone, custom source controls, run, Home/Jarvis delivery, explicit Library save, desktop/phone/200% zoom, keyboard/reduced motion | pass; isolated feeds and records, clean console |
| Incognito/token marks | every incognito state plus Aide token mark in desktop/phone and light/dark states | pass; reference ghost is unframed and unglowed; token owner visual approval remains open |
| KOKUEN capstone | Home, Apps, Files, Aide tools, Andromeda, Docs, Notes, Journal, System, Settings | pass; light/dark, mobile, reduced motion, partial states, 200% zoom, clean console |
| PhotoKit | real macOS availability/status plus intercepted permission/import calls | pass; no owner Photos prompt or library read |
| Remote services | WebDAV/S3 protocol and failure simulations | pass; owner endpoints and credentials intentionally unavailable and untouched |

Measured browser budgets remained within the existing Phase 10 limits: coldish boot p95 919.04ms,
Credits 209.73ms, navigation p95 75.86ms, and locale switching p95 42.10ms. The final Python
performance gate measured warm server p95 values of 4.48ms for `/`, 3.57ms for health, 4.64ms for
localization options, and 27.73ms for Credits.

## Design-system and anti-slop recheck

- [x] Finished apps own one compact identity in their header or rail; no `<app> / alles` crumb or
  repeated oversized app-name landing title is present.
- [x] Visible choices use custom KOKUEN dropdowns, switches, segmented controls, dialogs, and menus;
  no visible native select, checkbox, radio, or OS context menu is used as product UI.
- [x] The universal switch retains the rounded track, circular knob, accessible switch semantics,
  disabled state, visible focus, and 44px target.
- [x] Content is visible by default. No entrance animation can strand text or controls at opacity zero.
- [x] Desktop, mobile, and 200% zoom captures show deliberate reflow with no horizontal page overflow,
  clipped text, overlap, cut-off controls, edge-jammed copy, or ragged comparison columns.
- [x] Both themes preserve hierarchy and contrast; focus, selected, disabled, loading, empty, partial,
  offline, permission, error, retry, and recovery states remain readable without color alone.
- [x] Reduced motion leaves all content and controls usable. Hover/focus/pressed states do not move
  buttons, lift cards, animate underlines, or shift layout.
- [x] Product surfaces do not introduce marketing-template artifacts such as split heroes, pricing
  cards, glowy pills, fake app windows, testimonial cards, gradient text, radial halos, or pre-footer
  CTA slabs. Those landing-page-only rules are otherwise not applicable to this dense local app UI.
- [x] Shadows, borders, icons, typography, grain, and color stay within the documented KOKUEN system;
  there is no botched glass, all-around bloom, icon tile, decorative rule, unreadable text, or clipped
  grain over content in the inspected captures.
- [x] Real pointer, keyboard, focus return, mobile, theme, zoom, reduced-motion, console, and page-error
  checks were run with throwaway data. Representative captures were inspected at original resolution.

## Commands and versions

Final environment: Python 3.14.6, uv 0.11.22, Node v26.5.0, Docker 29.6.0, Ruff 0.15.22.

- `uv run --isolated --with-requirements requirements.txt --with playwright python -m unittest discover -s tests -t .`
  - 5,043 tests in 1,263.242s, OK, skipped 5.
- `node --test tests/js/*.mjs`
  - 444 passed, 0 failed, 0 skipped.
- `ALLES_RUN_ACTUAL_LIVE=1 python3 -m unittest -v tests.test_actual_live.ActualLiveGateTests.test_install_migrate_write_backup_restore_and_fresh_readback`
  - 1 passed in 39.981s.
- `uvx ruff check .` and `uvx ruff format --check .`
  - clean; 934 files formatted.
- `python3 scripts/generate_credits.py`
  - current manifest/notices/licenses validated.
- `uvx pip-audit -r requirements.txt`; npm audits in `integrations/actual` and `mobile`
  - no known vulnerabilities.
- `uvx bandit -r core routes services app.py cli.py -f json`
  - 0 high; reviewed medium candidates documented above.
- `git diff --check`; `git diff --cached --name-only`
  - clean whitespace; empty index.

Discarded runs are not counted as evidence: one plain `uv` command omitted project dependencies, one
shared top-level `ALLES_DATA` overrode the suite's per-test isolation, and two complete runs exposed
the stale short-password SSO and Photos fixtures. Each cause was fixed or corrected, focused tests
passed, and the authoritative full rerun above is from the final state.

## Open risks and intentional deferrals

- Original request 9 remains open only for the token glyph's owner visual approval. Incognito behavior
  is delivered and verified.
- The eight language catalogs have internal editorial/rendered review, not external native-speaker
  certification.
- Linux container behavior is physical; Linux systemd-user native behavior is simulated. macOS native
  behavior is physical.
- WebDAV and S3 use protocol simulations, not owner endpoints. This is intentional: owner credentials
  and data were outside scope.
- No autoreview result is claimed because the owner removed autoreview from this phase.

## Delivery boundary

No owner data was opened or changed. All verification uses isolated data and browser profiles. The
Git index remains empty. No autoreview, stage, commit, or push was performed for this gap-closure work.

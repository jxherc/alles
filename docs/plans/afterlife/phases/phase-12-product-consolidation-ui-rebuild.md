# Afterlife Phase 12 - product consolidation and interface rebuild

- **Status:** delivered locally on 2026-07-25; no commit or push created
- **Depends on:** delivered Phases 0 through 11
- **Safety boundary:** fake or throwaway data only; no owner database, Vault, files, credentials, Photos library, or normal `ALLES_DATA`
- **Git boundary:** do not stage, commit, or push unless the owner separately requests it

## Goal

Replace the crowded fifteen-app directory with nine coherent workbenches, give every destination one
KOKUEN navigation and focus grammar, rebuild Andromeda as a fast minimal search product with a separate
background verifier, and turn Server into the secure control surface for Alles and its services.

Home and Aide keep their approved information architecture. They receive only the shared shell,
navigation, focus, and placement corrections described here. Andromeda and every specialist workbench
receive a material redesign through approved standalone starters before the real interfaces change.

## Owner decisions

1. The visible specialist directory keeps the earlier grouped full-screen Apps format and contains exactly
   nine workbenches. Library remains its own destination.
2. Andromeda shows a compact cited answer before ordinary results.
3. One fast model produces that answer. A separate optional model verifies it in the background.
4. Verification especially protects current, latest, version, release, date, and other freshness-sensitive
   claims without delaying normal results or the first answer.
5. Server defaults to managing only Alles and Alles-owned services.
6. Extended host management is opt-in through one server-owned policy file. The app may edit only that
   typed policy, not arbitrary files or commands.

## Final product map

| Visible workbench | Owns | Retired standalone destinations |
|---|---|---|
| Plan | week, board, calendar, tasks, reminders, countdowns | Days |
| Inbox | mail and contacts | none |
| Docs | notes and journal | Journal |
| Files | storage locations, file operations, offline copies, gallery | Gallery |
| Library | books, saved reading, saved news, watchlist | none |
| Health | summary, history, habits | none |
| Finance | Actual-backed ledger, subscriptions, imports | none |
| Vault | passwords, passkeys, watchtower, browser access | Secrets label |
| Server | overview, services, search, models, backups, updates, logs, activity | System, Watch, Activity |

Home, Aide, Andromeda, Apps, and Settings remain primary product spaces. Old host names, view names,
deep links, and requested subsections redirect to the corresponding workbench section. Navigation
changes never move or rewrite owner records. Legacy duplicate chrome is removed only after route and
behavior parity passes.

## Universal interface contract

### App identity and navigation

- Every destination owns one 52px identity row. The app name appears once at the start and `home` is
  always reachable at the opposite end of the same identity region.
- There is no `<app> / alles` breadcrumb, bottom-edge Home link, duplicated app heading, or oversized
  app-name title.
- Aide places `home` where its search icon sits now. Task search becomes a full-width local field directly
  below the Aide identity row. The conversation, task tools, composer, and Projects behavior remain intact.
- Workspace apps place search or local filters below identity, never in the Home slot.
- Files and Gallery use one workspace. On small screens only one pane is visible, every drill-in has an
  explicit back action, and browser Back mirrors the visible pane when practical.
- The app directory keeps the earlier full-screen grouped format and shows three groups of three
  workbenches. Home shortcuts pin only these canonical destinations, not retired standalone routes.

### Focus and controls

- Split the current focus/active color role. Active selection may retain restrained Alles purple; focus
  becomes a high-contrast neutral token in both themes.
- Remove the full purple rectangle from the Home capture input and other text fields. Text-input focus uses
  a stable 2px neutral inset edge on the field boundary; button and menu focus uses a 2px neutral outline.
  Pointer and keyboard focus never change layout, glow, or shadow.
- Reduce Home capture to the documented 44px control rhythm and readable workbench width. Keep its mode,
  text, and save action aligned instead of stretching a tall focused box across the viewport.
- Continue to forbid visible native selects, checkboxes, radios, dropdowns, and context menus. Custom
  controls implement the correct ARIA role, keyboard pattern, disabled state, and focus return.

### Workbench shapes

- Plan uses timeline and list/board views over the same existing records; Countdowns becomes a Plan tab.
- Inbox uses the workspace pattern: local mailbox/contact navigation, one main list, one detail pane.
- Docs uses the workspace pattern: local knowledge sources, document list, document/editor pane. Journal,
  and related Markdown views are local sections, not separate apps.
- Files uses the workspace pattern. Gallery is a media section with its own browse tools but the same Files
  identity and back behavior.
- Library keeps books, saved reading, saved news, and watchlist as local sections of one destination.
- Health and Finance use dashboards with one real data grid or visualization, aligned values, and direct
  paths to their existing detailed lists.
- Vault uses the workspace pattern and preserves lock, reauthentication, passkey, browser-pairing, and
  recovery boundaries.
- Server uses the dashboard pattern described below.

## Andromeda: fast answer plus independent verification

### Search flow

1. Idle view shows one quiet Andromeda identity row and a centered search field. It does not add a hero,
   marketing copy, floating controls, or decorative search suggestions.
2. Submitting a query starts normal provider search immediately. Ordinary results render as soon as they
   arrive and remain usable even if either model fails.
3. The answer model receives a bounded evidence bundle and streams a compact answer with exact citations.
   It does not wait for the verifier.
4. When verification policy matches the query, a separate verifier job starts in the background using a
   separately configured model and verification evidence.
5. The results view keeps the search field in the top row, then category tabs and the compact answer with
   its verification state. Ordinary web results start in a separately labeled region after a major gap and
   structural boundary, rather than reading as part of the AI answer. Image, News, and Video retain their
   existing specialized result layouts.
6. A key answer highlights only its shortest decisive phrase after that exact phrase is found in the answer
   and cited evidence. Normal result rows stay open and use spacing rather than horizontal divider lines.
7. A new query cancels obsolete answer and verifier work. `!ai` continues to show normal results without
   either model.

### Model roles and settings

- Add explicit model roles `andromeda_answer` and `andromeda_verifier`. Existing `andromeda` role settings
  migrate to `andromeda_answer` without losing the selected endpoint or model.
- Server > Search and models owns provider order, result count, answer model, answer token/time limit,
  verifier mode, verifier model, verifier token/time limit, and remote-model privacy state.
- Verifier mode is a custom choice with `freshness-sensitive` as the default, plus `always`, `manual`, and
  `off`. A separate switch enables or disables background verification without erasing its configuration.
- Remote answer or verifier models keep the current explicit disclosure/confirmation boundary before the
  query or evidence leaves Alles. Local models require no network confirmation.

### Verification contract

- The verifier receives the query, current UTC date, configured local date/time zone, answer claims,
  exact answer citations, and a separately built bounded evidence bundle.
- For freshness-sensitive queries it prioritizes current official documentation, release notes, registries,
  and dated primary sources. It records `checked_on`, newest primary date/version seen, source conflicts,
  and whether independent corroboration was available.
- The verifier returns one verdict per claim: `verified`, `corrected`, `conflicting`, or `insufficient`.
  Every verified or corrected factual statement needs an exact quote and source URL. Server-side quote,
  entity, number, date, and version checks remain authoritative and reject unsupported model output.
- A correction becomes the visible answer only after server validation. The UI says `corrected after
  verification` and keeps a `what changed` disclosure; it never silently rewrites an answer.
- Verification state uses terse inline text: `checking`, `checked today`, `2 claims verified`, `1 claim
  corrected`, `sources conflict`, or `not independently checked`. It is not a colored badge wall.
- Failure never removes the fast answer or ordinary results. The answer is labeled `not independently
  checked` with a local retry action.
- Saved searches store the answer model identity, verifier model identity, claims, verdicts, citations,
  checked date, and corrections so reopening cannot imply a stale check is current.

## Server: secure management workbench

### Information architecture

- **Overview:** preserve the original live neofetch host readout and btop-style CPU, memory, network, disk,
  and process monitor as the primary machine view. The process table spans the available monitor width and
  carries a longer useful list instead of leaving a dead grid cell. Management summaries sit after it rather
  than replacing it. The runtime migration must call the existing `static/js/system.js` renderer; it must not
  redraw the Neofetch logos, graphs, meters, or btop process schema in a second implementation.
- **Services:** Alles plus registered owned services such as SearXNG and Actual, with status, logs, start,
  stop, restart, update, rollback, and ownership state where each action is actually supported.
- **Search and models:** Andromeda providers, answer/verifier model configuration, SearXNG lifecycle, model
  health, privacy class, and test actions.
- **Backups and storage:** automatic backup state, encrypted local/WebDAV/S3 targets, last verification,
  run-now, and staged restore entry points without duplicating the underlying settings records.
- **Updates:** installed revision, candidate revision, preflight, update, rollback, and restart handoff through
  the existing native ownership pipeline.
- **Logs and activity:** bounded runtime logs, audit records, background jobs, uptime checks, and the former
  Activity/Watch information.
- **Access policy:** current control mode, policy-file path, exact allowlist, validation state, and the typed
  policy editor.

### Server policy file

- Add `${ALLES_DATA}/server-policy.json` as the source of truth. Missing or invalid files fail closed to:
  `{ "control_mode": "owned_only", "host_services": [] }`.
- Supported modes are `owned_only` and `allowlisted_host`. There is no unrestricted shell, arbitrary process
  kill, wildcard service, or `all services` mode.
- `owned_only` may control only services with verified Alles ownership markers and may request an Alles
  restart/update only through its verified native supervisor.
- `allowlisted_host` may additionally control exact launchd or systemd service identifiers listed in
  `host_services`. Identifiers and manager type are schema-validated; commands, arguments, paths, globs,
  environment values, and inline scripts are rejected.
- The policy file is created atomically with owner-only permissions. Reads reject symlinks, non-regular files,
  ownership changes, unsafe permissions, malformed JSON, unknown fields, and duplicate identifiers.
- Server exposes only a schema-bound editor for this one file. It shows canonical JSON, validation errors,
  and a before/after diff; it cannot browse or edit another path.
- Saving `allowlisted_host` requires a loopback request, the device access profile, recent owner
  reauthentication, and an exact typed confirmation. Remote/LAN/public sessions may inspect the effective
  mode but cannot widen it.
- Every policy save and host-service action creates an audit record. A failed save keeps the previous file;
  a failed action does not change the displayed ownership or running state.
- Alles restart returns an accepted handoff before the supervisor restarts it. The client waits for the exact
  build/instance identity and offers retry instead of pretending a disconnected request succeeded.

## Approval and implementation sequence

### Gate 12A - truth map and starters

**Current state:** delivered. Fresh Browser, Computer Use, and Playwright starter evidence is recorded in
`../phase-12-design-review.md`, and the owner approved the exact files in
`docs/mockups/afterlife-phase12/` on 2026-07-24 before runtime integration began.

- Reconcile all fifteen current entries, deep links, view identifiers, browser modules, tables, APIs, jobs,
  settings, and existing tests into the nine-workbench map.
- Build standalone fake-data KOKUEN starters under `docs/mockups/` for: the nine-workbench shell and
  representative workbenches; Andromeda idle/results/verification; and Server management/policy editing.
- Include desktop, compact, phone, light/dark, 200% zoom, reduced motion, loading, empty, partial, error,
  offline, permission, long-content, focus, and back-navigation states.
- Run Browser, Computer Use, and Playwright checks against the exact starters. Do not modify the real app
  until the owner explicitly approves those exact files.

### Gate 12B - shared shell and navigation

**Current state:** delivered and rendered against the real application.

- Implement the nine-entry directory in the earlier grouped format, canonical pin targets, route compatibility, identity row, Home
  placement, Aide search relocation, Gallery/Files back behavior, neutral focus tokens, and Home capture fix.
- Update the design-system sources and add a decision record for the split active/focus roles.
- Verify navigation, focus return, keyboard, browser Back, mobile pane state, both themes, and cache identity.

### Gate 12C - Andromeda

**Current state:** delivered with focused backend/source tests and the real desktop/mobile browser gate.

- Split answer/verifier model roles and settings with compatibility migration.
- Add durable or restart-honest verifier jobs, server-side verdict validation, correction history, saved-search
  evidence, cancellation, timeout, privacy, and partial-failure handling.
- Migrate the approved minimal UI without changing provider, media-proxy, Library-save, Aide-handoff, or
  ordinary-result behavior.

### Gate 12D - Server

**Current state:** delivered with fail-closed policy tests, management-route tests, and rendered
desktop/mobile inspection.

- Add the fail-closed policy-file service and exact APIs for read, validate, diff, save, and supported actions.
- Compose existing health, stats, services, SearXNG, Actual, backup, update, log, audit, Watch, and Activity
  paths into the approved Server workbench.
- Prove owned-only defaults, loopback/reauth enforcement, allowlist parsing, symlink/permission rejection,
  atomic rollback, restart handoff, audit records, and unavailable-supervisor recovery.

### Gate 12E - specialist workbenches

**Current state:** delivered with compatibility/source tests and the full Phase 8 real browser gate.

- Migrate Plan/Days, Inbox, Docs/Journal, Library, Files/Gallery, Health, Finance, and Vault in small
  workspace-shape slices.
- Keep every existing record, mutation authority, privacy gate, recovery path, and compatibility route.
- Remove duplicate standalone entries and chrome only after route parity, main-task, empty/error, and mobile
  back-path tests pass for the replacement section.

### Gate 12F - capstone

**Current state:** delivered. Implementation, point-by-point design-system/anti-slop review, rendered
browser behavior, JavaScript, focused Python, and the clean isolated repository-wide Python suite are
green as of 2026-07-25. The final suite ran 5,488 tests in 3,078.444 seconds with 15 documented skips and
zero failures or errors. Ruff was unavailable in the worktree environment and was not installed merely
to manufacture a gate.

- Audit every visible destination and Settings once through Browser and once through Computer Use.
- Click every visible control with a real pointer; run complete keyboard paths and inspect console logs.
- Verify wide desktop, narrow desktop/tablet, phone, 200% zoom, light/dark themes, reduced motion, long data,
  offline, partial-provider, permission-denied, interrupted, and restart states with throwaway data.
- Run focused JavaScript/Python tests, then full JavaScript and Python suites, Ruff lint/format, generated
  credits if affected, and `git diff --check`.
- Re-read the full anti-slop law and design-system QA checklist point by point. Fix every applicable miss.
- Update `specifications.md` and mark this phase delivered only after implementation and fresh evidence agree.

## Acceptance criteria

- The Apps surface preserves the earlier grouped full-screen format, exposes exactly nine specialist
  workbenches, and has no retired standalone entry.
- Every destination has one app identity, one predictable Home path, visible neutral focus, and no navigation
  dead end; Gallery works on desktop, phone, browser Back, and keyboard.
- Aide retains its current work behavior with Home in the old search position and search immediately below.
- Andromeda renders ordinary results and a cited fast answer independently; background verification never
  blocks them and cannot mark unsupported claims verified.
- Freshness-sensitive checks name the actual checked date and primary evidence, and stale saved checks never
  appear current.
- Server is useful for management rather than monitoring alone, defaults to owned-only authority, and cannot
  widen host control remotely or through an arbitrary command/file payload.
- Old routes reach the correct new section without changing owner data.
- No visible native choice control, clipped content, giant repeated app name, purple full-field focus box,
  console error, broken control, or two-dimensional page overflow remains.
- No commit or push is created as part of this phase unless the owner separately requests it.

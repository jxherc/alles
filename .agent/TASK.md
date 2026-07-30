# current mission

## goal

Complete the approved KOKUEN v5 rebuild in the real Alles application. Preserve the graphite workbench
identity, provide one universal shell control from every space, centralize reusable interaction
primitives, migrate every shipped surface, publish an exhaustive interaction logic map, repeatedly
exercise every available function through isolated real-application runs, and finish with verified local
commits without pushing.

## status

The prior KOKUEN v3 follow-up has been recovered, reviewed, freshly verified, and preserved in local
commit `f22772491ba31d99d46f4ea9bfd64376a85a70f9`. The worktree was clean at the v5 start. The KOKUEN v5
shared runtime, machine-readable component contracts, 14-state vocabulary, 44px target layer, and single
universal shell are implemented and have passed their source, unit, and first real-application gate.
The Home, Aide, and Andromeda migration is complete and has passed focused and repeated real-application
gates. The nine specialist workbenches are next; no whole-rebuild completion has been claimed.

## requirements

- Work only in this history-rewrite worktree. Never modify `/Users/jxh/alles`.
- Preserve Home, Aide, and Andromeda as the three primary spaces.
- Expose exactly nine specialist apps: Plan, Inbox, Docs, Files, Library, Health, Finance, Vault, and
  Server.
- Provide one universal shell navigation/sidebar control from every space, outside app headers.
- Show each app name once. Remove duplicate oversized page titles and `app / alles` breadcrumbs.
- Centralize buttons, icon buttons, switches, fields, listboxes, menus, tabs, dialogs, sheets, command
  surfaces, and data views in reusable vanilla JavaScript primitives.
- Ship no browser- or operating-system-native selects, checkboxes, radios, or context menus as product
  UI.
- Enforce 44px targets, KOKUEN spacing, one perceived boundary, visible content before animation,
  unclipped focus, accessible keyboard behavior, and explicit operational states.
- Migrate in order: shared tokens/primitives/shell; primary spaces; nine specialist apps; Settings/setup;
  PWA/browser extension.
- Update the design-system sources and record system-wide decisions.
- Finish with zero KOKUEN hard errors and zero unexplained KOKUEN warnings.
- Preserve private owner data by using owned throwaway `ALLES_DATA` roots for all mutable verification.
- Create verified local commits with `jxherc <houjx0103@gmail.com>` and never push.

## implementation plan

1. Inventory every visible control, event authority, state transition, route, and shipped surface.
2. Stabilize KOKUEN v5 tokens, shared primitives, the universal shell, and the interaction-map schema.
3. Migrate Home, Aide, and Andromeda without changing their product authority or data model.
4. Migrate all nine specialist apps after the shared runtime is stable.
5. Migrate Settings, setup, the PWA, and the browser extension.
6. Generate the exhaustive human-readable and machine-verifiable interaction logic map.
7. Run repeated narrow and broad source, unit, integration, browser, keyboard, responsive, reduced-motion,
   offline, stale, partial, failure, and recovery checks on isolated real application instances.
8. Perform independent regression review, the full design-system and anti-slop audit, and verified local
   checkpoint commits without pushing.

## completed

- Read the complete applicable repository instructions, commit policy, KOKUEN v5 skill and required
  references, requested execution skills, project UI skill, design-system sources, specifications, and
  prior task state.
- Confirmed the target and protected worktrees and preserved all existing changes.
- Reviewed the KOKUEN v3 diff against its recorded task and checked that it contained no unrelated or
  private owner data.
- Passed 544 JavaScript tests, the exact 80-test Python contract suite, focused syntax/source checks, and
  the isolated real-app finished-surface browser gate.
- Inspected the fresh v3 desktop, mobile, light, reduced-motion, and 200% reflow captures.
- Created local baseline commit `f22772491ba31d99d46f4ea9bfd64376a85a70f9` with the required identity;
  no push occurred.
- Added the shared KOKUEN v5 runtime for primitive identity, state, busy repeat rejection, overlay focus
  boundaries, menus, and tabs, and upgraded the custom select to the complete single-select keyboard
  model.
- Added stable machine-readable contracts for actions, icon actions, fields, switches, selects, tabs,
  menus, dialogs, sheets, command, data views, and feedback across the complete 14-state vocabulary.
- Replaced the duplicated cross-app controls with one persistent shell trigger and one modal navigation
  sheet backed by the same three-primary plus nine-specialist registry as universal command.
- Removed the repeated Aide, Andromeda, and specialist Home actions and the old profile launcher, and
  reduced route identity to one app name without the `app / alles` crumb.
- Updated KOKUEN components, patterns, foundations, brand, responsive behavior, QA, product sources, and
  system decisions for the v5 universal contract.
- Passed 551 JavaScript tests, 9 design-system Python contracts, syntax and diff checks, and a live
  isolated Andromeda-to-Home shell, focus-return, navigation, and rendered graphite inspection.
- Migrated Home, Aide, and Andromeda to the frozen v5 shell: the global rail remains reachable, Aide
  exposes one explicit mobile identity when its local sidebar is closed, and Andromeda's idle footer and
  settings sheet clear the rail at every checked width.
- Updated the Home, Aide, Andromeda, combined Phase 4, and finished-surface browser gates to exercise
  the universal registry instead of removed local Home and Apps controls.
- Passed 552 JavaScript tests, the Home/Apps desktop and mobile gate, Aide's complete desktop/mobile
  interaction gate, Andromeda's dark/light desktop/mobile gate, the finished-surface family gate, and
  the combined repeated Aide/Andromeda/settings gate. Fresh phone captures were inspected after repair.

## in progress

- Specialist migration and state reconciliation for the exact nine app workbenches.
- Deterministic interaction and component inventory for the current application.

## remaining

- Nine specialist-app migration.
- Settings, setup, PWA, and browser-extension migration.
- Exhaustive interaction logic map and reconciliation tests.
- Repeated real-application functional exercise and full regression verification.
- Final anti-slop audit, design-system QA, local commits, and no-push handoff.

## issues or blockers

- No current implementation blocker.
- Live provider accounts, destructive host/network operations, and owner infrastructure remain outside
  ordinary local verification. Those flows must stay fail-closed and be reported as externally blocked
  unless an owned disposable environment is available.

## verification ledger

- KOKUEN v3 JavaScript baseline: **passed** - 544 tests, 0 failures.
- KOKUEN v3 focused Python baseline: **passed** - 80 tests, 0 failures.
- KOKUEN v3 finished-surface browser gate: **passed** - real isolated application across primary and
  specialist surfaces, Settings, phone widths, light appearance, reduced motion, and 200% reflow.
- KOKUEN v3 visual inspection: **passed** - fresh gate captures inspected at desktop and phone sizes.
- KOKUEN v3 checkpoint: **passed** - local commit identity and clean post-commit status verified; no push.
- KOKUEN v5 shared source gate: **passed** - JavaScript syntax, 551 JavaScript tests, 9 design-system
  contracts, and diff validation.
- KOKUEN v5 shared real-app gate: **passed** - one shell from Andromeda, exact destination registry,
  modal focus/Escape/restore behavior, authenticated navigation to Home, and fresh rendered inspection.
- KOKUEN v5 primary-space source gate: **passed** - 552 JavaScript tests and diff validation.
- KOKUEN v5 Home gate: **passed** - desktop/mobile loading, capture repeat rejection and retry, pinned
  navigation, shell registry, cross-host return, and single-host paint order.
- KOKUEN v5 Aide gate: **passed twice** - desktop/mobile tasks, projects, context, composer, attachments,
  permission, effort, model, message rail, work panel, terminal, keyboard, and shell behavior.
- KOKUEN v5 Andromeda gate: **passed repeatedly** - desktop/mobile, dark/light, search, normal/media
  results, overview, provider settings, custom choices, partial data, managed search, and shell return.
- KOKUEN v5 primary visual audit: **passed** - Home, Aide, shell, and repaired Andromeda phone/desktop
  captures inspected; no clipped panel or hidden primary identity remains.
- KOKUEN v5 whole-application migration and verification: **in progress** - no completion claim yet.

## boundaries

- Owner `.env`, databases, vaults, uploads, logs, generated model files, and normal `data/` are private.
- Mutable server and browser work requires a unique temporary data root and ownership sentinel.
- Preserve unrelated worktree changes and never clean, reset, or overwrite them.
- Do not push any commit without a separate explicit request.

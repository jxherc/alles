# current mission

## goal

Align the shipped Alles interface and its repository design contract with KOKUEN v3. Preserve the
existing visual identity and geometry, upgrade the real universal command surface to the new interaction
contract, repair any defects exposed by rendered verification, and finish with fresh regression and
real-browser evidence. Do not commit or push this follow-up unless separately requested.

## status

The KOKUEN v3 token/document migration, universal command implementation, setup-dialog race repair, and
rendered verification are complete. The full JavaScript suite, focused Python suites, and isolated
finished-surface browser gate pass. The final source/diff and anti-slop review is complete. These
follow-up changes are uncommitted and unpushed.

## locked product decisions

- Keep the current Docs editor, unified Settings, automatic Aide mode, and owner-configured Discord bot.
- Give Aide typed app-owned operations for every legitimate Alles function.
- Keep Auto as the safe default. Full Access becomes confirmation-free only after deliberate fail-closed
  Server activation, recent owner authentication, and an unrestricted-access warning.
- Reuse open source selectively: vendor small permissive components; run large products as pinned managed
  companions behind Alles-native interfaces.
- Prepare AdGuard Home and Nginx Proxy Manager only when prerequisites pass; activation requires guided
  network preflight and tested rollback.
- Support only legitimate provider authentication. CLIProxyAPI remains an owner-managed external endpoint.
- Keep Actual Budget canonical and use aggregator-first read-only bank synchronization with import
  fallbacks. Never scrape bank applications or store bank passwords.
- Use disposable data, accounts, and networks for destructive or sensitive verification.
- Treat standalone KOKUEN starters as optional reasoning tools, never approval gates.
- Use the KOKUEN v3 spacing sequence `0, 4, 8, 12, 16, 24, 32, 48, 64` while preserving the shipped
  geometry of existing surfaces during token-name migration.
- Keep universal command visually quiet and keyboard-first: one labelled dialog, one combobox, one
  listbox, honest states, deterministic focus, and no native choice controls.
- Do not commit or push the current follow-up without a separate owner request.

## implementation plan

1. Reconcile the new KOKUEN skill with the tracked design system and existing runtime aliases.
2. Upgrade the real universal command surface without changing Alles's established product identity.
3. Add source, registry, and browser regressions for semantics, keyboard, states, themes, phone, zoom,
   reduced motion, native-control exclusion, overflow, focus return, and console state.
4. Exercise the finished surfaces on a fresh isolated server and inspect the rendered captures.
5. Recheck the affected diff against KOKUEN, the repository QA contract, and the complete anti-slop law.

## current progress

- Migrated the tracked primitive and semantic spacing contracts to KOKUEN v3, added stable `--ui-*`
  aliases, and mechanically remapped old `--k-space-6`/`--k-space-8` consumers so existing 24px/32px
  geometry did not inflate to 32px/64px.
- Updated the product, component, pattern, output, QA, and project-skill documents so standalone starters
  are optional and the rendered application is the completion gate.
- Rebuilt universal command as an accessible dialog/combobox/listbox with deterministic option identity,
  pointer and full keyboard navigation, focus trap/return, request sequencing, and distinct idle,
  loading, empty, permission, unavailable, and error states.
- Removed the browser-native cancel glyph from universal command while keeping mobile search input hints.
- Repaired first-run setup so stale asynchronous loads and duplicate automatic openings cannot steal
  focus from another dialog or reopen after a successful dismissal.
- Added the command contract to the authoritative feature registry and regenerated the catalog and
  acceptance matrix.
- Passed the complete isolated finished-surface browser gate and inspected the resulting desktop, phone,
  light/dark, reduced-motion, and 200%-zoom captures.
- Recovered the real `dev-afterlife` worktree and confirmed it contains extensive owner-owned changes.
- Reconciled the approved program with the original owner-authored Obsidian roadmap and current code.
- Confirmed the existing Discord bot integration is the desired integration; OpenClaw is out of scope.
- Confirmed existing managed-service patterns for SearXNG and Actual can host independently licensed
  companions without copying their applications into Alles.
- Confirmed the existing durable Jarvis choice flow is a useful base but is not yet a general Aide
  `ask_user` capability.
- Added the authoritative 26-row registry, schema validator, generated catalog/acceptance matrix, and
  reconciliation test. Fresh proof maps every current route owner, CLI command, registered job,
  automation action, Aide tool, and interactive main-HTML control.
- Reproduced and traced the Files browser failure. The Phase 12 workbench deliberately hides the nested
  legacy brand row; the gate still clicked its retired Home button. The gate now exercises the visible
  universal workbench Home action and passes its full desktop, recovery, mobile, theme, zoom, operation,
  focus-return, and console scenario on a fresh isolated server.
- Built `docs/mockups/afterlife-completion/` as the exact integrated KOKUEN starter for Files scopes and
  vault transfer, Aide selectable questions, legitimate provider auth, read-only bank sync, and guided
  AdGuard/NPM activation. Its real browser gate passes desktop, 200%-equivalent width, phone, keyboard,
  dialog, focus, theme, blocked-state, overflow, and console checks. Individual rendered surfaces were
  inspected and corrected for compact titles and phone rhythm.
- Shipped Aide's typed `ask_user` capability across foreground and background runs, durable Jarvis
  records, reload/resume, cancellation, keyboard and pointer choice cards, free text, and Discord answer
  handling. A real isolated browser run proved the model pauses, survives reload, accepts an answer, and
  resumes the same run at desktop and phone widths with a clean console.
- Fixed the shared mobile drawer so crossing into phone width closes the off-canvas sidebar, and aligned
  fresh-browser Auto mode with the server's safe `full_auto` default while malformed stored state still
  fails closed to approval mode.
- Expanded generated credits to 497 validated records, including every required named reference, nine
  distinct inspiration entries, and zero manifest gaps. Manual-source refresh now preserves independently
  validated package evidence instead of weakening the strict full refresh.
- Shipped explicit model-provider authentication metadata and safe routing: API keys for OpenAI, Claude,
  Kimi, and DeepSeek; a separate owner-managed proxy type; and Gemini desktop OAuth with PKCE/state,
  encrypted refresh credentials, loopback-only callback, five-minute refresh, revoke, project/quota
  disclosure, and no consumer-session import. The real Settings surface passes clean desktop and phone
  browser checks; live external-account acceptance remains blocked until disposable credentials exist.
- Added typed, app-owned Aide operations for approved Files locations and durable operations, Finance
  accounts/transactions/import profiles, owned Server services, AdGuard management, and Nginx proxy
  hosts. Mutations use app scopes and never expose stored service credentials to the model.
- Shipped read-only SimpleFIN and Plaid connectors with encrypted tokens, cursoring, deduplication,
  removal, disconnect state, and reviewed major-bank import fallbacks. Focused Finance tests pass; live
  provider acceptance remains blocked without disposable accounts.
- Shipped the external Obsidian vault workflow: keep external, copy into Alles, or verified move into
  Alles with hash inventory, space/conflict preview, rollback snapshot, preserved links, and automatic
  rollback when its Files location cannot be created.
- Shipped pinned AdGuard Home and Nginx Proxy Manager companion foundations with prepare-without-start,
  exact listener preflight, dual ownership, activation rollback, encrypted API credentials, native
  AdGuard management, and native Nginx proxy-host/certificate management. Real listener activation is
  intentionally blocked until it can run inside an isolated network.
- Reconciled the registry and generated catalog with these implementations. Every runtime route owner,
  control, command, job, action, and Aide tool maps exactly once again.
- Added a benchmark-informed execution registry for all 120 registered delivery and real-computer tasks.
  The validator rejects missing features or scenarios, unavailable models, and max-effort primary routes;
  the generated plan records the resolved model and effort even after acceptance status changes.
- Corrected the universal specialist sidebar so the same control collapses the workbench rail plus nested
  Docs and Files rails, and verified desktop/mobile, themes, keyboard, focus, zoom, and reduced motion.
- Tightened Andromeda decisive-answer emphasis to highlight only supported answer substrings rather than
  unrelated versions or publication dates, and verified the real cited-search surface in Browser and
  macOS Safari.
- Fixed Aide Scheduled navigation to await its News workbench initialization. The real News scenario now
  covers cadence, source testing, run-now, explicit Library save, Jarvis gating, keyboard, phone, zoom,
  reduced motion, and a clean console.
- Rechecked Home, Apps, Plan, Docs, Library, setup, passwords, extension, model authentication, selectable
  Aide questions, Files, and the Phase 8 specialist surfaces against isolated real application instances.

## work in progress

- None. The scoped KOKUEN v3 migration, implementation, rendered verification, and final audit are
  complete.

## remaining

- The acceptance matrix intentionally retains thirteen blocked external-environment rows. No row is
  treated as passed merely because its local implementation and automated tests are green.
- Live provider, bank, device, mail/calendar/contact, Discord, S3/WebDAV, and managed-service checks may
  require owner-supplied disposable credentials or external infrastructure. These must remain visibly
  blocked or unavailable until exercised.
- Network-destructive AdGuard/NPM activation and Linux lifecycle scenarios must run only in a disposable
  VM or isolated test network.

## verification ledger

- KOKUEN v3 source contracts: **passed** - exact spacing/token alias, design-document, component, and
  generated registry checks are green.
- Universal command: **passed** - real pointer and keyboard use at desktop and phone widths; Home/End,
  arrow navigation, Enter, Escape, Tab trap, active descendant, focus return, error state, action/result
  layout, light/dark, reduced motion, 200% zoom, overflow, native-control exclusion, and clean console.
- Setup modal arbitration: **passed** - focused source/API tests plus the real fresh-install dismissal flow;
  stale setup work no longer steals focus from universal command.
- Full JavaScript suite: **passed** - 544 tests in 3.705 seconds with no skips or failures.
- Focused Python suites: **passed** - 80 setup, Obsidian, credits, design-system, registry, and manifest
  tests in 2.208 seconds.
- Finished-surface browser gate: **passed** - the current real application across Files, Home, Apps,
  command, specialists, Aide, Andromeda, Docs, Server, Settings, themes, phone widths, and 200% zoom in
  18.195 seconds.
- Final affected-surface anti-slop audit: **passed** - no decorative gradient, glow, shadow, pill, icon
  tile, entrance-hidden content, native search glyph, native choice control, clipped text, moving hover,
  dead action, or unexplained oversized heading remains in universal command. Its functional boundary,
  gutters, type, states, focus treatment, selected row, and responsive reflow were checked in the final
  captures.
- Current Files real-browser scenario: **passed** - full `tests/pw_phase7_files_real.py` on a fresh
  throwaway server after correcting its stale pre-consolidation Home selector.
- Registry reconciliation: **passed** - four focused tests cover runtime owners, commands, jobs, actions,
  Aide tools, interactive controls, and generated evidence parity.
- Standalone completion starter: **passed** - real Chromium at desktop, 200%-equivalent width, and phone,
  with reduced motion, keyboard choices, dialogs/focus return, themes, blocked activation, overflow, and
  clean console.
- Aide selectable questions: **passed** - focused Python and JavaScript tests plus the real isolated Aide
  browser flow at desktop and phone widths, including background execution, reload/reattach, keyboard and
  pointer input, free text, model continuation, native-control exclusion, overflow, and clean console.
- Credits inventory: **passed** - generated-manifest check and 13 focused tests over 497 records, all ten
  required references, nine inspiration entries, and zero metadata/license/source gaps.
- Model authentication: **passed locally** - 64 focused backend tests plus clean isolated desktop/phone
  browser proof for API-key/proxy metadata, Kimi preset, Gemini OAuth start, keyboard, native-control
  exclusion, overflow, encrypted secrets, migration, refresh/revoke, and clean console. Live Google and
  provider-account flows remain **blocked** pending disposable credentials.
- Finance connectors: **passed locally** - 106 focused Finance/migration tests and the rendered Finance
  connection surface; live Plaid/SimpleFIN accounts remain **blocked** pending disposable credentials.
- Files external vault workflow: **passed** - 38 Python transfer/API tests, 70 JavaScript Files contracts,
  and the real isolated desktop/phone browser scenario for Alles/Connected, copy/move/rollback, Gallery
  return, conflict recovery, keyboard, focus, overflow, theme, and clean console.
- Managed companions: **passed locally** - lifecycle, encrypted-client, API, ownership, Aide, and Server
  UI contract tests plus real unavailable-state desktop/phone and Computer Use inspection. Docker
  preparation and DNS/proxy activation remain **blocked** pending a disposable VM or isolated network.
- Gallery active navigation: **passed** - removed the stale purple active state, refreshed the shell/cache
  identity, and verified the actual Gallery surface in the isolated in-app Browser.
- Server workbench: **passed locally** - actual desktop/phone Browser and macOS Computer Use checks covered
  nine-app navigation, Neofetch/btop overview, companion unavailable states, keyboard tabs, overflow, and
  native-choice exclusion with a clean console. Connected service actions remain blocked as recorded.
- Full Python suite: **passed** - 5,552 tests in 3,394.451 seconds with 15 expected environment-gated skips.
- Full JavaScript suite: **passed** - 541 tests in 10.220 seconds with no skips or failures.
- Registry/inventory contracts: **passed** - 15 focused tests plus syntax compilation and `git diff
  --check`; 888 routes, 120 mapped tables, 26 jobs, every Aide tool, every CLI command, every automation
  action, and every interactive main-HTML control reconcile exactly once.
- Static lint: **unavailable** - neither the `ruff` executable nor Python module is installed in this
  worktree.
- User server: **preserved** - the pre-existing port 6769 process uses a custom non-test `ALLES_DATA`,
  predates the finalized backend, and is not tracked by the CLI safety PID file. It was not forcibly
  restarted or pointed at owner data; all current-code browser proof used isolated owned test data.
- Acceptance matrix: **recorded honestly** - 13 passed, 13 blocked, 0 unchecked, 0 partial, 0 failed, and
  0 falsely promoted from local coverage alone.
- Final visual law review: **passed for affected surfaces** - the latest actual Home, Apps, Aide, News,
  Andromeda, Plan, Docs, Files, Gallery, Library, Server, setup, passwords, and extension surfaces were
  inspected at representative desktop and phone widths; changed interactions were exercised by pointer
  and keyboard; spacing, clipping, contrast, focus, responsive overflow, custom controls, reduced-motion
  contracts, and console state were checked. No remaining visible defect was found in those surfaces.

## boundaries

- Owner data, `.env`, databases, vaults, uploads, logs, and model files are outside test scope.
- All server, browser, migration, backup, and integration work uses a throwaway `ALLES_DATA` with an
  ownership sentinel.
- Preserve every unrelated worktree change. Never clean, reset, or overwrite the dirty tree.
- The prior completed delivery commit remains intact. The current KOKUEN v3 follow-up is not staged,
  committed, or pushed.

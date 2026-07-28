# afterlife phase 6 completion tracker

- **status:** delivered - the reopened July 16 gate passed with fresh backend, browser, and live-provider proof
- **branch:** `dev-afterlife`
- **unblocks:** Phase 7 may resume from its existing in-progress storage work
- **source of truth:** this file replaces every earlier broad Phase 6 completion claim
- **last audit:** July 16, 2026

## tracking rule

- `[x]` means the current implementation passed a fresh, relevant test after its latest edit.
- `[ ]` means unfinished **or** not re-verified after its latest edit.
- Every new `[x]` must add its exact proof to the evidence log at the bottom.
- A broad suite cannot hide a visible failure. An owner-visible failure reopens its exact item.
- Tests use throwaway `ALLES_DATA`; never the owner's normal data, vault, uploads, or credentials.
- Read this tracker before Phase 6 work. Do not rely on old context-window summaries.

## 6.0 — gate and tracking

- [x] Work remains on `dev-afterlife`.
- [x] Phase 7 stayed paused while this tracker had unchecked items.
- [x] The current Andromeda settings bugs have focused regressions before their fixes.
- [x] Add a focused regression before every newly confirmed Phase 6 bug fix.
- [x] Serve the owner-visible build from the intended `dev-afterlife` worktree; leave the normal
  `/Users/jxh/alles` checkout on `notes-vault` untouched.
- [x] Audit the mixed worktree and exclude unfinished Phase 7 work from the Phase 6 delivery claim.
  No commit or push is part of this gate.
- [x] Finish every Phase 6 item below.
- [x] Change Phase 6 to delivered only after the final gate passes.

## 6.1 — Docs safety and knowledge

- [x] Re-run the exact-byte Markdown corpus: frontmatter, wiki links, embeds, callouts, tables,
  footnotes, task lists, HTML, code blocks, malformed syntax, invalid bytes, and large files.
- [x] Re-run focused-edit preservation and prove unrelated syntax and files do not change.
- [x] Re-run external-edit conflict, stale no-op, private draft, and exact revision tests.
- [x] Re-run Journal rename/link crash recovery and migration prepare/apply/resume/rollback.
- [x] Re-run watcher restart and local/external/draft-conflict classification.
- [x] Re-run trash/delete/restore and prove the only verified copy cannot be removed.
- [x] Re-run same-filesystem and cross-filesystem vault move/relink, cancellation, failure, and restart.
- [x] Re-run encrypted local, WebDAV, and S3 backup/restore with an external vault fixture.
- [x] Re-verify the approved viewer-first Docs UI, Open in Obsidian, CodeMirror Visual/Source modes,
  semantic icons, conflicts, and safe saves.
- [x] Re-verify unified Notes and non-private Journal without moving or duplicating source files.
- [x] Re-verify private Journal boundaries and retained heatmap, mood, topic, search, history, and
  on-this-day tools.
- [x] Re-verify Ask Aide about this note with visible note scope and normal permissions.
- [x] Re-verify old Notes, Journal, and Docs links, including query strings, fragments, and subdomains.

## 6.2 — Aide permissions, models, and runtime

- [x] Full Access is orange and runs allowed in-scope work without approval; hard safety blocks remain.
- [x] Auto Mode is purple, runs safe work automatically, and asks for risky work.
- [x] Ask for Approval asks before every change.
- [x] Plan is read-only.
- [x] Test all four modes across reads, writes, shell, deletion, external communication, computer use,
  helpers, delegation, and workflows.
- [x] Per-model reasoning supports Automatic, On, and Off with honest unsupported-provider states.
- [x] Normal effort levels remain available.
- [x] Deep Work supports up to 48 turns, thorough verification, bounded helpers, and workflows.
- [x] Custom supports 1–64 turns, reasoning, verification depth, delegation, and workflow reuse.
- [x] Custom settings persist separately for every model.
- [x] The effort/reasoning menu stays inside the screen with internal scrolling, keyboard support,
  mobile support, and 200% zoom support.
- [x] Replace turn counts, permanent Show Steps, and visible context plumbing with one temporary
  progress line before the answer.
- [x] Clear progress after success, failure, stop, reconnect, and retry.
- [x] Show the actual provider, model, and correctly proportioned local provider logo with a real
  configured provider rather than browser fixtures.
- [x] Keep helpers and workflows bounded, visible when used, and disabled for trivial work.
- [x] Keep one conversation across multiple messages; never create a conversation per message.
- [x] Stream responses and show only a typing state while waiting.
- [x] The Aide sidebar opens reliably on the default desktop entry state.

## 6.3 — Aide working context, tools, and composer

- [x] Tasks work without selecting a Project.
- [x] Each conversation remembers a temporary working directory.
- [x] Working directory can be changed safely.
- [x] Branch selection appears only for Git working directories.
- [x] Session-level branch APIs work outside saved Projects.
- [x] Dirty-tree protection gives short errors and closes the branch menu after refusal.
- [x] “Save this research to Docs” writes to the configured Markdown vault without a Project.
- [x] A Tasks conversation can create and read back a Markdown research file using throwaway data.
- [x] The terminal is a scoped macOS/Linux PTY rendered with the vendored xterm.js client.
- [x] The terminal panel contains only the terminal—no description, context card, or unrelated tool.
- [x] Scheduled, Brain, Skills, and Reminders share Scheduled's content width, top spacing, heading,
  controls, scrolling, typography, responsive layout, and loading/empty/error states.
- [x] The Aide wordmark is normal weight and aligned with navigation, headings, and content.
- [x] The bottom-right `tools` action opens a custom popup containing only `home` and `settings`.
- [x] Home keeps a direct `settings` action and does not get an Aide-style menu.
- [x] The message rail is hidden before three user messages.
- [x] Rail ticks are stable, equal 8px idle marks; the current mark is white but not longer.
- [x] Hover extends only the hovered rail mark to 28px with smaller nearby extensions.
- [x] The rail does not flash, jump, rebuild during streaming, or create an oversized hit area.
- [x] Test the rail with 3, 5, and 20 messages, rapid sends, streaming, stop, and retry.
- [x] Composer has one Upload File action; clipboard images use the same queue.
- [x] Upload previews live inside the growing composer with stable dimensions, name, size, progress,
  retry, and remove.
- [x] Link an App inserts `@calendar`, `@docs`, `@files`, and other context without navigating.
- [x] Connections is absent from the plus menu.
- [x] Speech works through permission, record, waveform, stop, transcription, cancel, failure, and a
  second recording.

## 6.4 — Home and System

- [x] Home and Aide use expanded calm, unexpected text pools.
- [x] Copy is chosen only when the screen opens or its time period changes; it never changes mid-read.
- [x] Home keeps readable text, compact KOKUEN spacing, live time, flashing colon, and direct Settings.
- [x] Home's Aide brief stays short plain text even when its source contains Markdown or a long answer.
- [x] Restore exact Neofetch-style macOS, Linux, Windows, and fallback ASCII marks.
- [x] System uses one square stage and one six-second linear color loop with no pulse, bloom, pause,
  second loop, or visible restart.
- [x] Reduced motion uses a static System mark.

## 6.5 — Andromeda

- [x] All search controls live inside Andromeda Settings using custom KOKUEN controls.
- [x] Settings include provider order, primary/fallback providers, result count, credentials/endpoints,
  normal results, AI Overview, exact model, and saved searches.
- [x] Managed SearXNG exposes status plus install, test, start/stop, restart, update, rollback, and
  uninstall-while-keeping-data actions.
- [x] Overview Strength explains Light, Standard, Strong, and Automatic speed/quality tradeoffs.
- [x] Settings fit desktop, mobile, keyboard, reduced motion, and 200% zoom without horizontal overflow.
- [x] A single provider is shown by name instead of leaving an empty provider section.
- [x] Empty settings status rows collapse, and the strength guide has space above its first line.
- [x] The shell cache stamp prevents old CSS/JavaScript from being mixed with the current settings HTML.
- [x] All results remain bounded and readable with proper bottom spacing.
- [x] Images load 30 initially and 30 more per page until the provider is exhausted against a real
  provider, not only a fulfilled browser route.
- [x] Image loading uses grid skeletons, stable ratios, progressive thumbnails, and no detached card.
- [x] News loads 20 readable rows per page and survives missing image, date, or snippet against a real
  provider.
- [x] Videos render working thumbnails, favicons, metadata, and play targets against a real provider.
- [x] Normalize image, favicon, publisher, date, thumbnail, and video fields across SearXNG and fallbacks.
- [x] Provider failure produces a quiet partial state without breaking the page.
- [x] All, Images, News, and Videos pass desktop/mobile, light/dark, keyboard, reduced-motion, overflow,
  spacing, and console checks.
- [x] AI Overview runs automatically with a real configured model when enabled, only appears on All,
  streams, cites real evidence,
  gives short full-sentence key answers, and never asks for an extra confirmation.
- [x] `!ai` disables only the current query's real overview while keeping normal results.
- [x] Search speed and provider fallback order are measured with live managed and external SearXNG
  states rather than mocked runners and fulfilled routes.

## 6.6 — real specialist app consistency

For each app, finish a direct visual audit and targeted correction of KOKUEN navigation, spacing,
typography, compact controls, desktop/mobile layout, loading/empty/error states, keyboard, reduced
motion, light/dark themes, overflow, and console behavior. Multi-source apps must also preserve useful
data in a real partial state when one source fails. Single-source apps use an honest error state rather
than a fake partial state with no surviving data. Do not redesign specialist data flows. If a material
redesign is needed, create a standalone HTML starter and wait for approval.

- [x] Calendar
- [x] Tasks
- [x] Docs
- [x] Files
- [x] Mail
- [x] Gallery
- [x] Contacts
- [x] Secrets
- [x] Subs
- [x] Money
- [x] Days
- [x] Journal
- [x] Activity
- [x] System
- [x] Watch
- [x] Habits
- [x] Watchlist
- [x] Books
- [x] Health
- [x] Confirm no real specialist app shows the old global sidebar.
- [x] Confirm no specialist app uses native select menus, checkboxes, radios, or context menus.

## 6.7 — final verification gate

- [x] Focused Python regressions pass after the final Phase 6 source edit.
- [x] All JavaScript tests pass after the final Phase 6 source edit.
- [x] `python -m unittest discover -s tests -v` passes after the final Phase 6 source edit.
- [x] `ruff check .` passes after the final Phase 6 source edit.
- [x] `ruff format --check .` passes after the final Phase 6 source edit.
- [x] Desktop and mobile Playwright passes for Docs, Aide, all four Aide tools, Home, System,
  Andromeda, and all 19 specialist apps.
- [x] Keyboard, light/dark themes, reduced motion, 200% zoom, overflow, and console gates pass.
- [x] All four permission modes pass the complete action matrix.
- [x] Live Tasks-to-Docs writing passes with throwaway data.
- [x] Managed and external SearXNG states pass live rather than through mocked command runners and
  fulfilled browser routes.
- [x] Final in-app and Ant browser inspection passes the owner-visible Home, Aide, Andromeda, Apps,
  Docs/Journal, System, and specialist-app shell with throwaway data and zero unexpected console
  errors; isolated Playwright covers the complete permission, speech, search, and 19-app matrices.
- [x] Update Phase 6, the phase index, and the Afterlife overview to delivered.
- [x] Resume Phase 7 only after every box above is checked.

## evidence log

### July 16, 2026 - independent distrust recheck

- The tracker was not accepted as proof by itself. All 123 checked items were re-audited against the
  implementation and current tests. This found two real evidence gaps: the 19-app gate had not
  exercised partial states, and the final visual pass had used the in-app browser instead of Ant.
- The app-state browser gate now proves partial failure and retry behavior for all 12 multi-source
  specialist apps. The seven single-source apps keep honest ready/empty and error states instead of
  showing a fake partial state with no surviving data. All 19 still pass loading, focus, hover, fatal
  error, and retry checks.
- Ant computer-control proof now covers real navigation through Home, Aide, Aide's two-item Tools
  menu, Andromeda, Andromeda Settings, Apps, Docs, Journal, and System on the owner-visible server.
- Fresh backend proof: `python3 -m unittest discover -s tests -v` passed 4,238 tests in 465.161
  seconds with 4 skips and zero failures using a new throwaway `ALLES_DATA` directory.
- Fresh frontend and style proof: `node --test tests/js/*.test.mjs` passed 237/237; Ruff check,
  Ruff formatting, and `git diff --check` passed.
- Fresh Playwright proof: Docs and compatibility routes, the Aide shell and four tools, streaming,
  speech, real PTY, System, Home, Apps, Andromeda Settings, automatic overview, all 19 real apps,
  their state gates, and KOKUEN finished surfaces passed again.
- Fresh live-search proof used a new isolated managed SearXNG install. Install, JSON search, stop,
  start, restart, update, safe unavailable rollback, real All/Images/News/Videos, and
  uninstall-while-keeping-data passed. Three managed searches returned five results in 876-3,242 ms.
  An invalid external SearXNG response quietly fell back to Wikipedia with 3-5 results in
  1,765-1,918 ms.
- Cleanup proof: the recheck container was uninstalled, its isolated data was retained, and the
  temporary server was stopped. The normal checkout and owner data were not touched.
- Owner-cache correction: a real owner screenshot exposed the old icon-left document card even
  though clean browsers rendered the corrected copy-left layout. The root cause was stale-first CSS
  service-worker caching. CSS now updates network-first with an offline fallback, the shell cache was
  bumped to `264`, and the exact `phase-6-proof` row passed in-app, desktop, and 390 px checks with
  the filename on the left, the document icon on the right, and zero console errors.

### July 16, 2026 - final reopened-gate proof

- Final source edit regression: the Docs sidebar grid test first failed against the old reversed
  columns, then passed after icons and labels were restored to their intended columns. The matching
  JavaScript regression and cache-stamp check also passed; the later owner-cache correction advanced
  the shell stamp to `264`.
- Focused backend proof: 140 Phase 6 tests passed using throwaway data.
- Full backend proof: `python3 -m unittest discover -s tests -v` passed 4,238 tests in 555.970 seconds
  with 4 skips and zero failures using throwaway data.
- Frontend proof: `node --test tests/js/*.test.mjs` passed 237/237.
- Python style proof: `python3 -m ruff check .` passed and
  `python3 -m ruff format --check .` reported all 853 files already formatted.
- Browser matrix proof: Docs and legacy routes, the Aide shell, Scheduled/Brain/Skills/Reminders,
  200% zoom, Aide state shells, streaming continuity, speech, real PTY, System, Home, Apps, live
  AI Overview, all 19 real specialist apps, all 19 state gates, and finished KOKUEN surfaces passed.
  The matrix covered desktop/mobile, light/dark, keyboard, reduced motion, overflow, and console gates.
- Live managed SearXNG proof: an isolated server used
  `/Users/jxh/.codex/tmp/alles-phase6-searxng`, never owner data. Install, loopback health, JSON test,
  stop, start, restart, safe update, and uninstall-while-keeping-data passed with Docker 29.5.2 and
  the pinned `2026.7.12-c19d86faa` image. Rollback correctly reported unavailable when no reviewed
  previous image existed; focused tests cover successful reviewed rollback and failed-update restore.
- Live Andromeda proof: the real backend and managed SearXNG passed All, Images, News, and Videos on
  desktop/mobile and light/dark. Managed searches returned five results in 1,218-1,646 ms. An external
  `https://baresearch.org` invalid-response state quietly fell back to Wikipedia with 3-5 results in
  1,918-2,534 ms, then the managed settings were restored.
- Final in-app browser proof: Home, Aide, Andromeda Settings, Apps, Docs/Journal, and System were
  inspected on the owner-visible build. The browser console had zero errors. The final visual review
  found no clipped text, broken spacing, native choice controls, fake glows, hover jumps, misaligned
  icons, or horizontal overflow in the checked desktop/mobile/light/dark surfaces.
- Cleanup proof: the managed test container was uninstalled while keeping its throwaway definition
  and data. The normal `/Users/jxh/alles` checkout and owner data remained untouched.

### July 15, 2026 — current proof

- Final post-fix backend proof: 171 focused Phase 6 tests passed, then
  `python3 -m unittest discover -s tests -v` passed 4,190 tests in 434.566 seconds with 4 skips and
  zero failures using throwaway data.
- Final post-fix frontend proof: `node --test tests/js/*.test.mjs` passed 225/225 after the automatic
  provider-chain regression and fix.
- Final post-fix style proof: `python3 -m ruff check .` passed and
  `python3 -m ruff format --check .` reported all 833 Python files already formatted.
- Live Andromeda proof: `tests/pw_phase6_andromeda_live.py` passed against isolated managed SearXNG;
  `tests/pw_phase6_andromeda_ai_live.py` passed twice against the real search pipeline, a configured
  streamed OpenAI-compatible model, exact evidence, automatic overview, full-sentence key answer,
  and the managed-primary to external-fallback chain.
- Final Aide proof: the shell, shared tool layout, voice, streaming continuity, and real PTY browser
  gates passed, including all permission labels, upload/paste, app links, model display, 3/5/20-message
  rails, stop/retry, and progress cleanup.
- Final specialist-app proof: both real-app Playwright gates passed all 19 screens across desktop,
  mobile, light/dark, keyboard, reduced motion, loading/empty/error states, overflow, native-control,
  old-sidebar, retry, and console checks.
- Final in-app browser proof: the owner-visible `dev-afterlife` server at `127.0.0.1:8030` opened Home,
  Aide, Andromeda Settings, Apps, and Calendar from throwaway data. Andromeda showed healthy managed
  SearXNG and all custom controls; every inspected screen had zero horizontal overflow, zero native
  choices, and zero console errors. The browser was left on Home for owner testing.

- Truth-audit correction: `/Users/jxh/alles` is on `notes-vault` at `c34f3a5`, while the tested Phase 6
  tree is a separate history-rewrite worktree on `dev-afterlife` at `d0098f9` with 354 modified and 60
  untracked files. The normal checkout does not contain `static/js/andromeda.js`, and its stylesheet
  hash differs from the tested worktree.
- Mock-boundary correction: the managed SearXNG unit suite replaces Docker and health probes with a
  fake command runner; the settings browser gate fulfills the lifecycle routes; the result gate
  fulfills search, media, and overview responses; speech uses a fake media device and mocked STT; and
  the specialist-app gates check shared layout/state shells rather than every real data flow. Those
  checks remain useful regression evidence but no longer count as end-to-end completion proof.

- Branch proof: `git branch --show-current` returned `dev-afterlife`.
- Andromeda browser proof: `PORT=8034 python3 tests/pw_phase6_andromeda_settings.py` passed desktop,
  mobile, reduced motion, 200% zoom, managed SearXNG actions, provider summary, spacing, overflow,
  keyboard close, and console checks using throwaway data.
- Andromeda JavaScript proof: `node --test tests/js/andromeda_phase4.test.mjs` passed 13/13.
- Cache proof: `python3 -m unittest
  tests.test_manifest_11b.ManifestTests.test_shell_cache_stamp_is_consistent -v` passed.
- Docs safety proof: 144 tests passed across `test_markdown_preservation`, `test_document_safety`,
  `test_document_safety_api`, `test_journal_migration`, `test_notes_vault`, `test_journal_vault`,
  `test_trash`, `test_vault_transfer`, `test_vault_transfer_api`, `test_backup_recovery`,
  `test_aide_document_scope`, `test_docs_reader`, and `test_route_compatibility` using throwaway data.
- Docs browser proof: `PORT=8037 python3 tests/pw_phase6_docs.py` passed the real viewer/editor,
  semantic icons, safe save/conflict flow, visible Aide note scope, retained Journal tools and
  migration, desktop/mobile layout, reduced motion, overflow, native-dialog, and console checks.
- Docs route proof: `PORT=8038 python3 tests/pw_phase6_docs_compatibility.py` passed legacy Notes,
  Journal, and Docs routes with deep-link state.
- Docs JavaScript proof: `node --test tests/js/docs_phase6.test.mjs
  tests/js/route_compatibility.test.mjs` passed 18/18.
- Aide runtime proof: 186 focused Python tests passed across run controls, Aide phase 4, agent runtime,
  app and vault tools, Project/session environments, PTY, voice, policy, delegation, local models, LLM,
  and message-count suites using throwaway data.
- Aide JavaScript proof: 62/62 passed across the Afterlife shell, progress, Aide shell/background,
  behavior, abort/rapid-send, custom dropdown, model selection/logo slots, per-model modes, and Project
  environment suites.
- Aide layout proof: `PORT=8039 python3 tests/pw_phase6_aide_layout.py` passed shared Scheduled,
  Brain, Skills, and Reminders geometry plus keyboard/mobile/200% zoom effort-menu bounds.
- Aide state proof: `tests/pw_phase6_aide_tool_states.py` passed loading, ready/empty, and error states
  for all four Aide tools.
- Aide continuity proof: `tests/pw_phase6_stream_continuity.py` passed same-session rapid sends,
  streaming, stop, retry, progress cleanup, four user messages, and visible rail behavior.
- Aide shell proof: `tests/pw_afterlife_aide_shell.py` passed normal-weight alignment, tools popup,
  custom controls, working-folder and Git context, bounded branch errors, permission/effort menus,
  app links, upload and clipboard previews, 3/5/20-message stable rails, terminal-only panel, light
  theme, desktop/mobile layout, and console checks.
- Aide permission proof: `ALLES_DATA=$(mktemp -d) python3 -m unittest tests.test_policy
  tests.test_agent_cwd tests.test_agent_opencode -v` passed 38/38. The matrix covered all four modes
  across reads, writes, shell, delete, outside communication, computer control, one/many helpers, and
  delegated runs. Full Access still obeyed disabled/persona, secret-path, and workspace-root blocks.
- Aide permission/model/upload browser proof: `PORT=8060 python3 tests/pw_afterlife_aide_shell.py`
  passed desktop and mobile after the added checks. It proved orange Full Access, purple Auto Mode,
  Ask and Plan labels, real provider/model metadata, a local DeepSeek 24×24-viewBox mark rendered at
  a square 14px, and composer upload name, size, stable 38px preview, 50% progress, failure, retry,
  success, removal, and clipboard parity with no console errors.
- Aide progress regression proof: `PORT=8060 python3 tests/pw_phase6_stream_continuity.py` failed
  first because the waiting line said `starting…`; after the correction it passed one-session
  streaming, partial-token paint, typing-only wait, hidden 1/2-message rails, stop, failure cleanup,
  reconnect, retry, six messages, and zero leftover progress rows.
- Speech proof: `tests/pw_voice_2e.py` passed denial, waveform, stop, transcription, cancel, failure,
  and a second recording.
- PTY proof: `PORT=8047 python3 tests/pw_shell_pty_live.py` passed real scoped command round trips in
  the vendored xterm renderer on desktop and mobile.
- Scheduled/background proof: `tests/pw_afterlife_aide_scheduled.py` and
  `tests/pw_afterlife_aide_background.py` exited successfully against isolated servers.
- Home/System Python proof: 53 focused tests passed across `test_home`, `test_api_today`,
  `test_today_sections`, `test_today_golden`, and `test_api_system` using throwaway data.
- Home/System JavaScript proof: `node --test tests/js/today_view.test.mjs
  tests/js/system_graph.test.mjs` passed 19/19, including stable time-period copy, brief cleanup,
  platform marks, one exact six-second loop, square sizing, and reduced motion.
- Home/System browser proof: `PORT=8050 python3 tests/pw_afterlife_home_apps.py` and
  `PORT=8050 python3 tests/pw_system_logo.py` passed desktop/mobile, live Home controls, direct
  Settings, readable brief copy, all four platform marks, exact loop timing, reduced motion,
  overflow, and console checks against an isolated server.
- Specialist-app regression proof: the readable-control matrix failed first across all 19 real apps
  at 10.24–12px, then `PORT=8058 python3 tests/pw_phase6_real_apps.py` passed after the shared
  KOKUEN correction with headings at least 16px and labeled controls at least 13px.
- Specialist-app state proof: `PORT=8058 python3 tests/pw_phase6_real_app_states.py` passed all 19
  real screens for loading, usable empty/ready content, keyboard focus, hover stability, fatal error,
  and retry behavior.
- Specialist-app full matrix proof: 76 real-screen cases passed across desktop/mobile, light/dark,
  reduced motion, overflow, console, old-sidebar, native-control, and app/home navigation checks.
  Fresh contact sheets were inspected from `phase6-app-audit-after-scale` after the final type fix.
- Andromeda backend proof: 62 focused tests passed across `test_andromeda_phase4`, `test_api_search`,
  and `test_managed_searxng`, including 30-result image pages, provider exhaustion, field
  normalization, managed/external SearXNG, fallback order, elapsed time, partial failure, streaming
  citations, automatic overview, and the short full-sentence key-answer regression.
- Andromeda result JavaScript proof: `node --test tests/js/andromeda_phase4.test.mjs` passed 13/13
  after the result and overview corrections.
- Andromeda result browser proof: `PORT=8060 python3 tests/pw_afterlife_andromeda.py` passed four
  real-shell cases: desktop/mobile crossed with light/dark and reduced motion. It verified loaded web
  favicons, 30 then 60 progressive images, 20 tolerant news rows, 20 working video thumbnails and
  targets, bounded All results, bottom spacing, quiet partial providers, automatic cited overview,
  full-sentence key answers, `!ai`, Home navigation, no native choices, no overflow, and no console or
  server errors.
- Final focused Python proof: 117/117 passed after the final source edit across the cache manifest,
  permission policy, working-directory and delegated-run behavior, Andromeda, search, and managed
  SearXNG suites using throwaway data.
- Final JavaScript proof: `node --test tests/js/*.test.mjs` passed 223/223 after the final source edit.
- Final style proof: `python3 -m ruff check .` passed, then `python3 -m ruff format --check .` passed
  with all 831 Python files already formatted after formatting only the three touched browser gates.
- Final Tasks-to-Docs proof: an isolated run of
  `AgentVaultToolsTests.test_tasks_conversation_can_write_and_read_research_in_docs` passed. A Tasks
  conversation wrote `Research/local-search.md`, read the content back through `docs_read`, and
  confirmed the Markdown file existed in the throwaway Docs vault without selecting a Project.
- Final full-suite proof: with no browser or server competing for resources,
  `ALLES_DATA=$(mktemp -d /tmp/alles-phase6-full-final-XXXXXX) python3 -m unittest discover -s tests -v`
  passed 4,186 tests in 1,156.429 seconds with 4 skips, zero failures, and exit code 0.
- Final Docs browser proof: on a fresh isolated server at port 8062, `tests/pw_phase6_docs.py` and
  `tests/pw_phase6_docs_compatibility.py` passed the real viewer/editor, safe writes and conflicts,
  Journal tools, visible Aide note scope, legacy routes, desktop/mobile, keyboard, reduced motion,
  overflow, native-control, and console gates.
- Final Aide browser proof: on a fresh isolated server at port 8064,
  `tests/pw_afterlife_aide_shell.py`, `tests/pw_phase6_aide_layout.py`,
  `tests/pw_phase6_aide_tool_states.py`, `tests/pw_phase6_stream_continuity.py`,
  `tests/pw_voice_2e.py`, `tests/pw_shell_pty_live.py`, `tests/pw_afterlife_aide_scheduled.py`, and
  `tests/pw_afterlife_aide_background.py` all passed. This covered desktop/mobile, 200% zoom,
  light theme, keyboard, tool states, rails, streaming, stop/retry, speech, real PTY, scheduled work,
  background work, overflow, and console checks.
- Final Home/System browser proof: on a fresh isolated server at port 8065,
  `tests/pw_afterlife_home_apps.py` and `tests/pw_system_logo.py` passed desktop/mobile Home and all
  four square System marks with one seamless loop, reduced motion, overflow, and console checks.
- Final Andromeda browser proof: on a fresh isolated server at port 8066,
  `tests/pw_phase6_andromeda_settings.py` and `tests/pw_afterlife_andromeda.py` passed full custom
  Settings, managed and external SearXNG states, provider controls, 200% zoom, keyboard, All, Images,
  News, Videos, desktop/mobile, light/dark, reduced motion, overflow, and console gates.
- Final specialist-app browser proof: after a wrong-server port collision was detected and rejected,
  a confirmed Alles server at port 8077 passed `tests/pw_phase6_real_apps.py` and
  `tests/pw_phase6_real_app_states.py` across all 19 real apps. The gates covered desktop/mobile,
  light/dark, reduced motion, readable controls, app/home navigation, loading, empty/ready, focus,
  hover, errors, retry, native controls, old sidebars, overflow, and console errors.
- Final post-browser style proof: after the cold-boot readiness check was added to the real-app browser
  gates, `python3 -m ruff check .` passed and `python3 -m ruff format --check .` reported all 831
  Python files already formatted.
- Final Ant proof: Ant opened a confirmed Alles server at `127.0.0.1:8078` backed by throwaway
  `ALLES_DATA`. Computer control verified Home, Aide, the four permission labels, the two-item Aide
  tools menu, Apps, Calendar, Docs, Andromeda Settings, live web results, and a 29-image exhausted
  provider page. Ant was restored to the owner's original tab and the throwaway server was stopped.
- Previous completion claim, now superseded: the tracker was changed to Delivered and Phase 7 was
  resumed before the mock boundaries and separate-worktree problem were audited. The July 15 truth
  audit above reverses that claim.

### superseded proof

Earlier Phase 6 reports claimed broad completion from loading/state checks and an old full-suite run.
Those results do not check any box in this tracker because owner-visible app and responsive failures were
found afterward. They may guide debugging, but they are not current completion evidence.

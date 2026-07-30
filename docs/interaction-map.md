# Alles interaction map

Generated from `features/registry.json` and `features/interaction-logic.json`. Run
`python scripts/generate_interaction_map.py`; do not hand-edit this file or its JSON peer.

This is an inventory, not a claim that blocked external scenarios were exercised. `external
blocks or gaps` records what cannot be proved from the local environment or registry contract.

Shared control contract: `static/js/kokuen.js`. It rejects repeated
activation while a control is `aria-busy=true`; individual rows retain any narrower gap.
The universal visible-state vocabulary is: `resting`, `hover`, `pressed`, `selected`, `disabled`, `busy`, `invalid`, `loading`, `empty`, `permission`, `offline`, `stale`, `partial`, `error`.

| feature | app | risk | implementation | acceptance | triggers | controls | tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| setup-security.owner-setup | setup | critical | shipped | passed | fresh owner setup<br>recent-owner reauthentication<br>resume interrupted setup | #setup-wizard | tests/test_api_setup.py<br>tests/test_auth.py<br>tests/test_server_config.py |
| home.capture-and-navigation | home | medium | shipped | passed | capture from Home<br>open every workbench<br>use Home at phone width | body<br>#app-drawer<br>#today-view<br>#home-view | tests/test_home.py<br>tests/test_today_golden.py<br>tests/pw_afterlife_home_apps.py |
| aide.conversation-and-execution | aide | critical | shipped | blocked | complete an Auto task<br>arm Full Access<br>inspect a redacted audit | #chat<br>#project-view<br>#models-view<br>#model-modal<br>#brain-view<br>#reminders-view<br>#aide-scheduled-view<br>#skills-view<br>#usage-view<br>#aide-work-panel | tests/test_agent_tools.py<br>tests/test_agent_runtime.py<br>tests/test_policy.py<br>tests/js/aide_afterlife_shell.test.mjs |
| aide.selectable-questions | aide | medium | shipped | blocked | answer by pointer<br>answer by keyboard<br>reload and resume<br>answer through Discord | none registered | tests/test_aide_questions.py<br>tests/test_agent_runtime.py<br>tests/test_jarvis_records.py<br>tests/test_jarvis_discord.py<br>tests/pw_aide_questions_real.py |
| andromeda.cited-search | andromeda | medium | shipped | blocked | search and open citations<br>toggle verification<br>render failed checks honestly | #andromeda-view<br>#compare-view<br>#search-modal | tests/test_andromeda_phase4.py<br>tests/js/andromeda_phase4.test.mjs<br>tests/pw_afterlife_andromeda.py |
| plan.tasks-calendar | plan | medium | shipped | passed | create and move a task<br>keyboard board navigation<br>create and delete an event | #plan-view<br>#tasks-view<br>#calendar-view<br>#days-view | tests/test_task_reorder.py<br>tests/test_api_calendars.py<br>tests/js/plan_board.test.mjs |
| inbox.mail-and-contacts | inbox | high | shipped | blocked | connect a disposable mailbox<br>send a test message<br>edit a test contact | #inbox-view<br>#mail-view<br>#contacts-view | tests/test_mail.py<br>tests/test_contact_events.py<br>tests/test_carddav.py<br>tests/test_caldav_sync.py |
| docs.documents-and-journal | docs | high | shipped | passed | edit and recover a document<br>rename with backlink preservation<br>migrate and roll back a journal entry | #docs-workbench-view<br>#wiki-view<br>#docs-dialog | tests/test_notes_vault.py<br>tests/test_vault_md.py<br>tests/test_journal.py<br>tests/test_journal_migration.py |
| files-photos.locations-and-media | files | critical | shipped | passed | browse Alles and Connected<br>copy move and roll back<br>open Gallery and return Home<br>resolve a vault conflict | #files-workbench-view<br>#files-view<br>#gallery-view<br>#photos-view<br>#files-preview-modal<br>#files-location-dialog<br>#files-transfer-dialog | tests/test_files_location_identity.py<br>tests/test_storage_locations.py<br>tests/test_file_operations.py<br>tests/test_vault_transfer.py<br>tests/test_vault_transfer_api.py<br>tests/js/files_phase7_real.test.mjs<br>tests/pw_phase7_files_real.py |
| library.reading-and-news | library | medium | shipped | passed | save and open a page<br>add and update a book<br>deliver a cited news brief | #library-view<br>#books-view<br>#read-view<br>#cookbook-view | tests/test_books.py<br>tests/test_read.py<br>tests/test_news.py |
| health.logs-and-habits | health | high | shipped | passed | log a synthetic measurement<br>complete a habit<br>inspect empty and partial summaries | #health-group-view<br>#health-view<br>#habits-view | tests/test_health.py<br>tests/test_habits.py |
| finance.actual-ledger | finance | critical | shipped | blocked | reconcile a disposable ledger<br>import statement fixtures<br>undo an import | #finance-view<br>#money-view<br>#subs-view | tests/test_actual_finance_canonical.py<br>tests/test_finance_imports_phase8.py<br>tests/test_money.py |
| finance.bank-connectors | finance | critical | shipped | blocked | connect Plaid sandbox<br>deduplicate transactions<br>expire and reconnect consent<br>disconnect and revoke | none registered | tests/test_finance_connectors.py<br>tests/test_finance_imports_phase8.py<br>tests/test_money_csv.py |
| passwords.vault-and-browser | passwords | critical | shipped | passed | pair the extension<br>fill an exact test site<br>reject a mismatched origin<br>revoke a browser | #vault-workbench-view<br>#vault-view | tests/test_vault_autofill.py<br>tests/test_browser_passwords.py<br>tests/js/browser_extension_phase9.test.mjs |
| server.management | server | critical | shipped | blocked | inspect neofetch and btop<br>restart a disposable service<br>reject an unsafe policy edit<br>perform update rollback | #server-workbench-view<br>#system-view<br>#watch-view<br>#activity-view | tests/test_api_system.py<br>tests/test_server_policy_phase12.py<br>tests/test_native_install.py |
| server.adguard-home | server | critical | shipped | blocked | prepare without activation<br>activate in isolation<br>inspect query statistics<br>roll back DNS | none registered | tests/test_managed_companions.py<br>tests/test_managed_companion_clients.py<br>tests/test_managed_companion_api.py<br>tests/test_aide_managed_companion_tools.py<br>tests/js/server_workbench_phase12.test.mjs |
| server.nginx-proxy-manager | server | critical | shipped | blocked | prepare without Docker<br>activate in isolation<br>create a proxy host<br>roll back service | none registered | tests/test_managed_companions.py<br>tests/test_managed_companion_clients.py<br>tests/test_managed_companion_api.py<br>tests/test_aide_managed_companion_tools.py<br>tests/js/server_workbench_phase12.test.mjs |
| integrations.owner-connectors | settings | critical | shipped | blocked | pair a Discord owner<br>connect and revoke MCP<br>test a signed webhook<br>disconnect an endpoint | none registered | tests/test_api_mcp.py<br>tests/test_jarvis_discord.py<br>tests/test_mcp_credentials_migration.py<br>tests/test_connections.py |
| integrations.model-authentication | settings | critical | shipped | blocked | connect Gemini OAuth<br>connect and revoke an API key<br>discover CLIProxyAPI models<br>show unsupported OAuth honestly | none registered | tests/test_model_auth.py<br>tests/test_model_catalog_migration.py<br>tests/test_model_providers.py<br>tests/test_llm.py<br>tests/pw_model_auth_real.py |
| automation.schedules-and-actions | aide | high | shipped | passed | create and pause a schedule<br>resume after restart<br>inspect a failed action<br>cancel a run | none registered | tests/test_automations.py<br>tests/test_chains.py<br>tests/test_proactive.py |
| localization.regional-settings | settings | medium | shipped | passed | use automatic region<br>override formats<br>switch reviewed languages<br>restart and preserve choices | #settings-modal | tests/test_localization_catalogs.py<br>tests/js/i18n.test.mjs |
| localization.credits | settings | high | shipped | passed | search named inspirations<br>open a local notice<br>show unavailable notice honestly | none registered | tests/test_credits_manifest.py<br>scripts/generate_credits.py |
| accessibility.interface-contract | all | high | shipped | passed | complete flows by keyboard<br>verify dialog focus return<br>test responsive and zoom states<br>test reduced motion and themes | none registered | tests/test_design_system_contract.py<br>tests/js/kokuen_command_contract.test.mjs<br>tests/pw_kokuen_finished_surfaces.py |
| extension-mobile.pwa-and-extension | home | high | shipped | blocked | install PWA<br>exercise offline and reconnect<br>pair and revoke extension<br>test mobile package | none registered | tests/test_capacitor_11b.py<br>tests/js/browser_extension_phase9.test.mjs<br>tests/test_manifest_11b.py |
| backup-recovery.lifecycle | server | critical | shipped | blocked | fresh macOS install<br>fresh Linux VM install<br>recover interrupted update<br>uninstall preserving data<br>restore and roll back | none registered | tests/test_automatic_backup.py<br>tests/test_backup_recovery.py<br>tests/test_native_install.py |
| developer-interfaces.api-cli | server | critical | shipped | passed | issue and revoke API token<br>call OpenAI-compatible API<br>reject scope escalation<br>run CLI tests | none registered | tests/test_api_tokens.py<br>tests/test_api_openai_compat.py<br>tests/test_capabilities.py<br>tests/test_shell_pty.py<br>tests/test_cli_safety.py |
## setup-security.owner-setup

Install, initialize, authenticate, and safely configure one owner without exposing private data.

- triggers: `fresh owner setup`, `recent-owner reauthentication`, `resume interrupted setup`
- authority and guards: `one-owner authentication and setup state`, `private data is not exposed`
- mutation or side effect: Creates or resumes owner configuration and authentication state.
- visible states: `loading`, `ready`, `busy`, `error`, `recovery`
- success: The owner reaches authenticated, configured state.
- failure: Setup or authentication errors remain visible.
- recovery: Resume interrupted setup or reauthenticate a recent owner.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Wizard choices use the shared radio model; the dialog traps focus and returns it on exit.
- control surfaces: `#setup-wizard`
- function surfaces: `routes.auth`, `routes.setup`, `routes.api_tokens`, `routes.status`, `install`, `uninstall`, `doctor`
- automated tests: `tests/test_api_setup.py`, `tests/test_auth.py`, `tests/test_server_config.py`
- acceptance evidence: Passed 2026-07-27: the fresh isolated Phase 9 setup/password browser gate completed first-run setup; setup, auth, server-config, recent-owner, and durable-resume backend regressions passed.
- external blocks or gaps: none registered

## home.capture-and-navigation

Capture work, review current context, open the nine workbenches, and receive local notices.

- triggers: `capture from Home`, `open every workbench`, `use Home at phone width`
- authority and guards: `local Home state`, `destination registry`
- mutation or side effect: Captures work and persists Home display preferences where enabled.
- visible states: `loading`, `ready`, `empty`, `partial`, `offline`, `error`, `busy`
- success: Captured work is visible and registered workbenches open.
- failure: Local notices retain failure or offline state.
- recovery: Retry is explicit where a Home section fails.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Shell navigation and capture are keyboard-operable with focus return.
- control surfaces: `body`, `#app-drawer`, `#today-view`, `#home-view`
- function surfaces: `app`, `routes.today`, `routes.briefing`, `routes.notify`, `routes.push`, `routes.timeline`, `day_events`, `reminders`, `calendar_reminders`
- automated tests: `tests/test_home.py`, `tests/test_today_golden.py`, `tests/pw_afterlife_home_apps.py`
- acceptance evidence: Passed 2026-07-27: the isolated Home/Apps gate captured one task, opened all nine workbenches, and passed desktop/phone layout, keyboard, retry, focus, overflow, and clean-console checks.
- external blocks or gaps: none registered

## aide.conversation-and-execution

Run model conversations, projects, memory, research, delegated work, and owner-approved local execution.

- triggers: `complete an Auto task`, `arm Full Access`, `inspect a redacted audit`
- authority and guards: `configured model provider`, `owner-approved tool and Full Access boundaries`, `redacted audit boundary`
- mutation or side effect: Creates conversations, projects, memories, delegated work, and approved local executions.
- visible states: `loading`, `ready`, `busy`, `partial`, `error`, `blocked`
- success: A completed run exposes its conclusion and retained audit controls.
- failure: Provider and policy failures remain visible without exposing secrets.
- recovery: Retry or continue only through the existing approval boundary.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Chat, work panel, menus, and dialogs use the shared keyboard/focus contract.
- control surfaces: `#chat`, `#project-view`, `#models-view`, `#model-modal`, `#brain-view`, `#reminders-view`, `#aide-scheduled-view`, `#skills-view`, `#usage-view`, `#aide-work-panel`
- function surfaces: `routes.agent`, `routes.chat`, `routes.sessions`, `routes.models`, `routes.local_models`, `routes.memory`, `routes.research`, `routes.rag`, `routes.textindex`, `routes.images`, `routes.skills`, `routes.delegation`, `routes.personas`, `routes.projects`, `routes.usage`, `routes.insights`, `routes.recall`, `routes.voice`, `user_model`, `insights`, `model_refresh`, `personal_reconcile`
- automated tests: `tests/test_agent_tools.py`, `tests/test_agent_runtime.py`, `tests/test_policy.py`, `tests/js/aide_afterlife_shell.test.mjs`
- acceptance evidence: Blocked 2026-07-27: local runtime, policy, typed-tool, Full Access, shell, and redacted-audit coverage passes, but completing a real model-backed Auto task requires a disposable configured model provider; no provider credential was supplied.
- external blocks or gaps: `Live model-backed Auto completion is externally blocked without disposable provider credentials.`

## aide.selectable-questions

Ask one to four durable questions with two to five choices, optional free text, reload/resume, cancellation, and Discord rendering.

- triggers: `answer by pointer`, `answer by keyboard`, `reload and resume`, `answer through Discord`
- authority and guards: `durable question record`, `two-to-five choices and optional free text`
- mutation or side effect: Persists an answer or cancellation for the durable question.
- visible states: `ready`, `busy`, `error`, `cancelled`, `blocked`
- success: Pointer or keyboard answer resumes the retained task after reload.
- failure: Invalid or unavailable delivery is shown without silently answering.
- recovery: Reload/reattach continues the same question; cancellation is durable.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Choices and free text are keyboard-operable.
- control surfaces: none registered
- function surfaces: none registered
- automated tests: `tests/test_aide_questions.py`, `tests/test_agent_runtime.py`, `tests/test_jarvis_records.py`, `tests/test_jarvis_discord.py`, `tests/pw_aide_questions_real.py`
- acceptance evidence: Blocked 2026-07-27: typed ask_user, durable agent/Jarvis state, cancellation, pointer, keyboard, free text, reload/reattach, model continuation, and Discord rendering pass focused tests and the real browser gate; answering through a live Discord bot requires disposable bot credentials not supplied.
- external blocks or gaps: `Live Discord delivery is externally blocked without disposable bot credentials.`

## andromeda.cited-search

Return fast web results, a compact cited answer, and optional independent freshness-aware verification.

- triggers: `search and open citations`, `toggle verification`, `render failed checks honestly`
- authority and guards: `search provider availability`, `separate model and verifier availability`
- mutation or side effect: Searches and optionally records a verification request; opening citations leaves Alles.
- visible states: `loading`, `ready`, `partial`, `error`, `blocked`
- success: Links-first results and citations render separately from an answer.
- failure: Unavailable model or failed checks are rendered honestly.
- recovery: Retry preserves the query path where available.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Search modal and result controls follow shared dialog/focus behavior.
- control surfaces: `#andromeda-view`, `#compare-view`, `#search-modal`
- function surfaces: `routes.andromeda`, `routes.search`, `routes.compare`
- automated tests: `tests/test_andromeda_phase4.py`, `tests/js/andromeda_phase4.test.mjs`, `tests/pw_afterlife_andromeda.py`
- acceptance evidence: Blocked 2026-07-27: live DuckDuckGo search, separated results, decisive snippet emphasis, citations, recovery controls, and honest model-unavailable state passed in Chromium, Safari, and Computer Use; compact answer and independent verifier execution require disposable model credentials.
- external blocks or gaps: `Compact answer and independent verifier need disposable model credentials.`

## plan.tasks-calendar

Manage tasks, Kanban, calendars, reminders, and countdowns through one workbench.

- triggers: `create and move a task`, `keyboard board navigation`, `create and delete an event`
- authority and guards: `task and calendar record validation`
- mutation or side effect: Creates, moves, edits, completes, and deletes task/calendar records.
- visible states: `loading`, `ready`, `empty`, `busy`, `error`, `recovery`
- success: Atomic task moves and calendar changes are reflected in the workbench.
- failure: Validation or persistence errors remain visible.
- recovery: History/details preserve a route back from failed editing.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Board navigation is keyboard-operable.
- control surfaces: `#plan-view`, `#tasks-view`, `#calendar-view`, `#days-view`
- function surfaces: `routes.tasks`, `routes.calendar`, `routes.calendars`, `routes.reminders`, `routes.days`
- automated tests: `tests/test_task_reorder.py`, `tests/test_api_calendars.py`, `tests/js/plan_board.test.mjs`
- acceptance evidence: Passed 2026-07-27: the rendered Plan gate created and moved tasks atomically, exercised keyboard board controls, details/history, desktop/phone/zoom reflow, and a clean console; calendar create/delete is covered by the isolated API and browser regressions.
- external blocks or gaps: none registered

## inbox.mail-and-contacts

Read and send mail and manage contacts through owner-configured connectors.

- triggers: `connect a disposable mailbox`, `send a test message`, `edit a test contact`
- authority and guards: `owner-configured mailbox and address-book connectors`
- mutation or side effect: Sends mail and edits contact records through configured connectors.
- visible states: `loading`, `ready`, `offline`, `error`, `blocked`
- success: Configured connector work updates cached mail or contacts.
- failure: Connector failure is visible and does not claim delivery.
- recovery: Retry depends on restoring the configured external connector.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Registered Inbox roots use the shared custom-control contract.
- control surfaces: `#inbox-view`, `#mail-view`, `#contacts-view`
- function surfaces: `routes.mail`, `routes.contacts`, `routes.caldav`, `routes.carddav`, `mail_outbox`, `ics_subscriptions`, `carddav_auto`
- automated tests: `tests/test_mail.py`, `tests/test_contact_events.py`, `tests/test_carddav.py`, `tests/test_caldav_sync.py`
- acceptance evidence: Blocked 2026-07-27: mail, SMTP outbox, contacts, CardDAV, and CalDAV implementations and isolated failure paths pass, but the three real-computer scenarios require a disposable external mailbox and address-book account; none was supplied.
- external blocks or gaps: `Live mailbox and address-book scenarios require disposable external accounts.`

## docs.documents-and-journal

Create, edit, search, link, recover, and migrate documents and journal entries.

- triggers: `edit and recover a document`, `rename with backlink preservation`, `migrate and roll back a journal entry`
- authority and guards: `local document and journal authority`, `backlink-safe rename and migration controls`
- mutation or side effect: Creates, edits, renames, restores, migrates, and rolls back documents and journal entries.
- visible states: `loading`, `ready`, `busy`, `error`, `recovery`
- success: Edits recover across reload; rename preserves backlinks; migration can roll back.
- failure: Conflicts and failed edits remain explicit.
- recovery: Draft/reload recovery and rollback are available.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Editor and dialogs have focused keyboard coverage.
- control surfaces: `#docs-workbench-view`, `#wiki-view`, `#docs-dialog`
- function surfaces: `routes.notes`, `routes.journal`, `routes.journal_migration`, `routes.vault_md`
- automated tests: `tests/test_notes_vault.py`, `tests/test_vault_md.py`, `tests/test_journal.py`, `tests/test_journal_migration.py`
- acceptance evidence: Passed 2026-07-27: the current Docs home and real Docs gates passed edit/draft/reload/recovery, backlink-safe rename, journal migration rollback, keyboard, responsive, focus, and clean-console checks on isolated data.
- external blocks or gaps: none registered

## files-photos.locations-and-media

Browse managed and approved locations, operate safely on files, keep explicit offline copies, and organize photos.

- triggers: `browse Alles and Connected`, `copy move and roll back`, `open Gallery and return Home`, `resolve a vault conflict`
- authority and guards: `approved storage location identity`, `file-operation and vault-conflict safeguards`
- mutation or side effect: Browses, copies, moves, rolls back, and organizes owner-approved files and media.
- visible states: `loading`, `ready`, `offline`, `error`, `busy`, `recovery`
- success: Selected location operations and Gallery return paths retain context.
- failure: Offline and conflict state is explicit.
- recovery: Rollback and conflict recovery are offered for safe operations.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Workbench dialogs and navigation return focus.
- control surfaces: `#files-workbench-view`, `#files-view`, `#gallery-view`, `#photos-view`, `#files-preview-modal`, `#files-location-dialog`, `#files-transfer-dialog`
- function surfaces: `routes.files`, `routes.file_operations`, `routes.offline_files`, `routes.storage_locations`, `routes.photos`, `routes.gallery`, `routes.uploads`, `routes.shared`, `blob_gc`, `clip_index`, `faces_index`, `photo_watch`
- automated tests: `tests/test_files_location_identity.py`, `tests/test_storage_locations.py`, `tests/test_file_operations.py`, `tests/test_vault_transfer.py`, `tests/test_vault_transfer_api.py`, `tests/js/files_phase7_real.test.mjs`, `tests/pw_phase7_files_real.py`
- acceptance evidence: Passed 2026-07-27: the real isolated Files gate covered Alles/Connected scopes, local operations, copy/move/rollback, external-vault conflict recovery, offline states, Gallery return Home, keyboard, focus, themes, phone/zoom, and a clean console.
- external blocks or gaps: none registered

## library.reading-and-news

Save reading, manage books, collect cited news, and keep cookbook material.

- triggers: `save and open a page`, `add and update a book`, `deliver a cited news brief`
- authority and guards: `owner-selected feeds and local reading/book records`
- mutation or side effect: Saves reading, updates books, runs and explicitly saves a news brief.
- visible states: `loading`, `ready`, `empty`, `partial`, `offline`, `error`, `busy`
- success: Saved content and cited briefs appear in their destination.
- failure: Independently successful data stays visible when a source fails.
- recovery: Explicit retry is available for failed loading paths.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Library controls use the shared contract.
- control surfaces: `#library-view`, `#books-view`, `#read-view`, `#cookbook-view`
- function surfaces: `routes.books`, `routes.read`, `routes.cookbook`, `routes.news`, `read_feeds`, `scheduled_news`
- automated tests: `tests/test_books.py`, `tests/test_read.py`, `tests/test_news.py`
- acceptance evidence: Passed 2026-07-27: the real isolated Library saved and opened example.com, archived it, added/rated/completed a book, and the News gate enabled, ran, cited, and explicitly saved a brief with desktop/phone/zoom and clean-console proof.
- external blocks or gaps: none registered

## health.logs-and-habits

Record health observations and track habits without presenting the app as medical care.

- triggers: `log a synthetic measurement`, `complete a habit`, `inspect empty and partial summaries`
- authority and guards: `local sensitive health context`, `non-medical presentation boundary`
- mutation or side effect: Records synthetic or owner-entered observations and habit completion.
- visible states: `loading`, `ready`, `empty`, `partial`, `error`
- success: Observation and habit changes render without medical claims.
- failure: Partial and empty summaries remain distinguishable.
- recovery: Retry preserves independently loaded data.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Health controls use the shared contract.
- control surfaces: `#health-group-view`, `#health-view`, `#habits-view`
- function surfaces: `routes.health`, `routes.habits`
- automated tests: `tests/test_health.py`, `tests/test_habits.py`
- acceptance evidence: Passed 2026-07-27: isolated Health and habit browser gates logged synthetic data, completed a habit, and checked baseline, anomaly, empty, and partial-summary states without medical claims.
- external blocks or gaps: none registered

## finance.actual-ledger

Use Actual Budget as canonical ledger and import statements read-only with provenance and undo.

- triggers: `reconcile a disposable ledger`, `import statement fixtures`, `undo an import`
- authority and guards: `Actual Budget canonical authority`, `read-only import provenance and conflict controls`
- mutation or side effect: Previews/applies statement imports and undoes imports with provenance.
- visible states: `loading`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Ledger/import authority and undo state remain visible.
- failure: Conflicts fail closed without silently changing canonical data.
- recovery: Undo/retry use the retained import identity.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Finance row actions and controls use shared semantics.
- control surfaces: `#finance-view`, `#money-view`, `#subs-view`
- function surfaces: `routes.money`, `routes.finance_actual`, `routes.finance_imports`, `routes.subscriptions`, `holdings_price`, `subscriptions`
- automated tests: `tests/test_actual_finance_canonical.py`, `tests/test_finance_imports_phase8.py`, `tests/test_money.py`
- acceptance evidence: Blocked 2026-07-27: canonical-authority, statement preview/apply/provenance/conflict/undo, and migration regressions pass, but reconciling a live disposable Actual ledger requires an installed disposable Actual service not available in this acceptance environment.
- external blocks or gaps: `Live disposable Actual service is unavailable for reconciliation acceptance.`

## finance.bank-connectors

Synchronize accounts read-only through SimpleFIN or Plaid with reconnect, revocation, deduplication, and reviewed bank import profiles.

- triggers: `connect Plaid sandbox`, `deduplicate transactions`, `expire and reconnect consent`, `disconnect and revoke`
- authority and guards: `SimpleFIN or Plaid consent`, `read-only connector boundary`, `reviewed import profiles`
- mutation or side effect: Connects, reconnects, disconnects, revokes, and deduplicates imported connector data.
- visible states: `loading`, `ready`, `error`, `blocked`, `recovery`
- success: Consent and connector state are retained with provenance.
- failure: Unsupported or unavailable connection is explicit.
- recovery: Reconnect or revoke requires the external provider boundary.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; use the parent Finance surface.
- control surfaces: none registered
- function surfaces: `routes.finance_connections`, `simplefin`, `plaid`, `actual-budget`
- automated tests: `tests/test_finance_connectors.py`, `tests/test_finance_imports_phase8.py`, `tests/test_money_csv.py`
- acceptance evidence: Blocked 2026-07-27: connector cursor/dedupe/consent/reconnect/revoke tests and reviewed Canadian/Chinese import profiles pass; live Plaid/SimpleFIN scenarios require disposable aggregator credentials not supplied. Chinese banks correctly remain statement and owner-authorized notification/email ingestion only.
- external blocks or gaps: `Live aggregator credentials are unavailable.`

## passwords.vault-and-browser

Store encrypted secrets and fill exact-site credentials through paired short-lived browser sessions without model plaintext.

- triggers: `pair the extension`, `fill an exact test site`, `reject a mismatched origin`, `revoke a browser`
- authority and guards: `encrypted unlocked vault`, `paired short-lived browser session`, `exact normalized origin`
- mutation or side effect: Pairs, fills selected credentials, locks, and revokes browser authority.
- visible states: `locked`, `ready`, `busy`, `error`, `recovery`
- success: Only the selected exact-site credential is released; it is never submitted.
- failure: Mismatched/broader authority is rejected.
- recovery: Lock, restart, computer lock, or revoke removes fill authority.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Vault controls use shared custom-control behavior.
- control surfaces: `#vault-workbench-view`, `#vault-view`
- function surfaces: `routes.vault`, `routes.browser_passwords`, `browser-extension`
- automated tests: `tests/test_vault_autofill.py`, `tests/test_browser_passwords.py`, `tests/js/browser_extension_phase9.test.mjs`
- acceptance evidence: Passed 2026-07-27: the real unpacked Chromium extension paired to a disposable vault, filled only the exact local fixture origin, never submitted, rejected broader authority, cleared its short session on restart, locked, and revoked cleanly.
- external blocks or gaps: none registered

## server.management

Inspect and control owned services, machine health, updates, logs, policy, and watched resources through fail-closed authority.

- triggers: `inspect neofetch and btop`, `restart a disposable service`, `reject an unsafe policy edit`, `perform update rollback`
- authority and guards: `owned-service policy`, `fail-closed lifecycle authority`
- mutation or side effect: Inspects owned resources and requests service, policy, watch, or update changes.
- visible states: `loading`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Permitted inspection or lifecycle state is rendered with audit context.
- failure: Unsafe policy edits are rejected.
- recovery: Update rollback restores prior selection and focus.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Server controls and rollback flows preserve focus.
- control surfaces: `#server-workbench-view`, `#system-view`, `#watch-view`, `#activity-view`
- function surfaces: `routes.system`, `routes.macos`, `routes.watch`, `start`, `stop`, `restart`, `status`, `logs`, `open`, `watch`
- automated tests: `tests/test_api_system.py`, `tests/test_server_policy_phase12.py`, `tests/test_native_install.py`
- acceptance evidence: Blocked 2026-07-27: Neofetch/btop, process layout, fail-closed policy editor, unsafe-edit rejection, lifecycle rollback tests, Safari, and Computer Use inspection pass; no registered disposable owned service or disposable update release was available for live restart/rollback.
- external blocks or gaps: `Live owned disposable restart and rollback targets are unavailable.`

## server.adguard-home

Prepare pinned AdGuard Home when supported and activate DNS only after preflight, backup, health checks, and rollback proof.

- triggers: `prepare without activation`, `activate in isolation`, `inspect query statistics`, `roll back DNS`
- authority and guards: `supported pinned companion`, `listener preflight`, `backup, health-check, and rollback proof`
- mutation or side effect: Prepares a companion and, only after preflight, can activate or roll back DNS.
- visible states: `unavailable`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Prepare does not activate the service.
- failure: Unsupported or unsafe activation remains unavailable.
- recovery: DNS rollback is required after activation.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; use the parent Server surface.
- control surfaces: none registered
- function surfaces: `adguard-home`
- automated tests: `tests/test_managed_companions.py`, `tests/test_managed_companion_clients.py`, `tests/test_managed_companion_api.py`, `tests/test_aide_managed_companion_tools.py`, `tests/js/server_workbench_phase12.test.mjs`
- acceptance evidence: Blocked 2026-07-27: pinned metadata, prepare-without-start, exact listener preflight, encrypted client/API, ownership, typed Aide tools, unavailable-state UI, and rollback tests pass; DNS activation and statistics inspection require a disposable VM or isolated network not available here.
- external blocks or gaps: `Activation and statistics require a disposable VM or isolated network.`

## server.nginx-proxy-manager

Prepare pinned Nginx Proxy Manager when Docker prerequisites pass and manage proxy hosts, certificates, access, updates, and rollback.

- triggers: `prepare without Docker`, `activate in isolation`, `create a proxy host`, `roll back service`
- authority and guards: `Docker prerequisites`, `pinned companion ownership and rollback controls`
- mutation or side effect: Prepares a companion and manages proxy/certificate/access lifecycle only when prerequisites pass.
- visible states: `unavailable`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Prepare-without-start preserves the inactive boundary.
- failure: Missing Docker or unsafe activation is explicit.
- recovery: Service rollback is required after activation.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; use the parent Server surface.
- control surfaces: none registered
- function surfaces: `nginx-proxy-manager`
- automated tests: `tests/test_managed_companions.py`, `tests/test_managed_companion_clients.py`, `tests/test_managed_companion_api.py`, `tests/test_aide_managed_companion_tools.py`, `tests/js/server_workbench_phase12.test.mjs`
- acceptance evidence: Blocked 2026-07-27: pinned metadata, Docker prerequisite handling, prepare-without-start, encrypted client/API, proxy-host/certificate UI, typed Aide tools, ownership, and rollback tests pass; live proxy activation requires a disposable Docker VM or isolated network not available here.
- external blocks or gaps: `Live proxy activation requires a disposable Docker VM or isolated network.`

## integrations.owner-connectors

Connect Discord, MCP, external endpoints, and signed webhooks with explicit health and revocation.

- triggers: `pair a Discord owner`, `connect and revoke MCP`, `test a signed webhook`, `disconnect an endpoint`
- authority and guards: `encrypted connector credentials`, `signed webhook and explicit health/revocation boundary`
- mutation or side effect: Pairs, connects, tests, disconnects, and revokes owner connectors.
- visible states: `loading`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Connector health and revocation state are explicit.
- failure: External delivery failure does not claim success.
- recovery: Reconnect/revoke remains owner-controlled.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; Settings owns the visible controls.
- control surfaces: none registered
- function surfaces: `routes.connections`, `routes.mcp`, `routes.jarvis`, `routes.webhooks`, `jarvis_scheduler`, `jarvis_outbox`, `jarvis_events`, `discord-bot`, `mcp`, `webhooks`, `external-openai-compatible`
- automated tests: `tests/test_api_mcp.py`, `tests/test_jarvis_discord.py`, `tests/test_mcp_credentials_migration.py`, `tests/test_connections.py`
- acceptance evidence: Blocked 2026-07-27: Discord, MCP, encrypted credential migration, signed webhook, health, and revocation regressions pass; real pairing and delivery require disposable external connector credentials and endpoints that were not supplied.
- external blocks or gaps: `Real connector pairing and delivery need disposable credentials/endpoints.`

## integrations.model-authentication

Connect model providers through legitimate API keys, supported OAuth, or an owner-managed OpenAI-compatible proxy with exact auth type and revocation guidance.

- triggers: `connect Gemini OAuth`, `connect and revoke an API key`, `discover CLIProxyAPI models`, `show unsupported OAuth honestly`
- authority and guards: `legitimate provider auth type`, `encrypted secret storage`, `revocation guidance`
- mutation or side effect: Connects, refreshes, discovers, or revokes provider credentials.
- visible states: `loading`, `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Supported auth type and provider state are shown accurately.
- failure: Unsupported OAuth is shown honestly.
- recovery: Refresh/revoke uses provider-specific flow.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Settings keyboard and overflow behavior has focused coverage.
- control surfaces: none registered
- function surfaces: `model_oauth_refresh`, `gemini-oauth`, `openai-api-key`, `claude-api-key`, `kimi-api-key`, `deepseek-api-key`, `cliproxyapi`
- automated tests: `tests/test_model_auth.py`, `tests/test_model_catalog_migration.py`, `tests/test_model_providers.py`, `tests/test_llm.py`, `tests/pw_model_auth_real.py`
- acceptance evidence: Blocked 2026-07-27: 64 focused provider/auth/routing tests and the real desktop/phone Settings gate pass API-key/proxy metadata, Kimi/DeepSeek guidance, Gemini PKCE start, encrypted secrets, refresh/revoke, keyboard, overflow, and clean console. Live provider OAuth/API-key connection requires disposable external credentials not supplied.
- external blocks or gaps: `Live OAuth/API-key acceptance needs disposable credentials.`

## automation.schedules-and-actions

Run durable schedules, chains, proactive work, and explicit automation actions with retry and audit state.

- triggers: `create and pause a schedule`, `resume after restart`, `inspect a failed action`, `cancel a run`
- authority and guards: `durable schedule/chain state`, `claimed occurrence and audit boundary`
- mutation or side effect: Creates, pauses, resumes, retries, cancels, and audits schedules and automation actions.
- visible states: `ready`, `busy`, `failed`, `uncertain`, `cancelled`, `recovery`
- success: Completed action state and audit history are retained.
- failure: Failed or uncertain external action stays visible; uncertain work is not auto-retried.
- recovery: Pause/resume, retry, and cancellation are explicit.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Scheduled controls use custom controls.
- control surfaces: none registered
- function surfaces: `routes.automations`, `routes.chains`, `routes.proactive`, `automations`, `proactive`, `create_note`, `create_task`, `notify`, `notify_digest`, `push`, `push_digest`
- automated tests: `tests/test_automations.py`, `tests/test_chains.py`, `tests/test_proactive.py`
- acceptance evidence: Passed 2026-07-27: the rendered Scheduled screen created and edited schedules with custom controls; automation and Jarvis regressions cover pause/resume, restart recovery, honest failed/uncertain actions, cancellation, retries, and audit history. Direct scheduled navigation is now awaited and the News acceptance gate passes.
- external blocks or gaps: none registered

## localization.regional-settings

Apply reviewed language catalogs and independent automatic or explicit region, timezone, clock, week, and currency preferences.

- triggers: `use automatic region`, `override formats`, `switch reviewed languages`, `restart and preserve choices`
- authority and guards: `reviewed language catalog`, `independent regional preference persistence`
- mutation or side effect: Selects automatic or explicit language, region, timezone, clock, week, and currency preferences.
- visible states: `loading`, `ready`, `error`, `recovery`
- success: Overrides survive restart.
- failure: Catalog failure is explicit without corrupting existing choices.
- recovery: Reopen Settings and retain the last persisted choice.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Settings custom controls are keyboard-operable.
- control surfaces: `#settings-modal`
- function surfaces: `routes.settings`, `routes.appearance`
- automated tests: `tests/test_localization_catalogs.py`, `tests/js/i18n.test.mjs`
- acceptance evidence: Passed 2026-07-27: unified Settings detected region/timezone automatically, used custom region and format controls, loaded all reviewed catalogs, persisted overrides, and passed the desktop/phone localization gate.
- external blocks or gaps: none registered

## localization.credits

Show dependencies, adapted sources, inspirations, revisions, licenses, source links, and required notices.

- triggers: `search named inspirations`, `open a local notice`, `show unavailable notice honestly`
- authority and guards: `generated license and source manifest`
- mutation or side effect: Searches and opens attribution/notice detail; it does not mutate owner data.
- visible states: `ready`, `empty`, `error`, `unavailable`
- success: Available local notices and evidence render.
- failure: Unavailable notice is stated honestly.
- recovery: Search or reopen detail without side effects.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Settings search/detail uses the shared contract.
- control surfaces: none registered
- function surfaces: none registered
- automated tests: `tests/test_credits_manifest.py`, `scripts/generate_credits.py`
- acceptance evidence: Passed 2026-07-27: 497 generated records have complete category, revision, license, source, and notice evidence; all required inspirations are distinct, Settings search/detail was exercised with Obsidian, and rendered desktop/phone credits states pass.
- external blocks or gaps: none registered

## accessibility.interface-contract

Keep controls custom, semantic, keyboard-operable, focus-visible, responsive, contrast-safe, and usable with reduced motion and 200 percent zoom.

- triggers: `complete flows by keyboard`, `verify dialog focus return`, `test responsive and zoom states`, `test reduced motion and themes`
- authority and guards: `semantic custom-control contract`, `reduced-motion and responsive preferences`
- mutation or side effect: No product record mutation; governs control behavior across surfaces.
- visible states: `ready`, `disabled`, `busy`, `loading`, `error`, `offline`, `partial`
- success: Custom controls remain keyboard-operable with focus return and visible state.
- failure: Contract violations must fail deterministic tests.
- recovery: Restore focus, preserve visible content, and retry through the owning feature.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: This feature is the cross-application keyboard/focus authority.
- control surfaces: none registered
- function surfaces: none registered
- automated tests: `tests/test_design_system_contract.py`, `tests/js/kokuen_command_contract.test.mjs`, `tests/pw_kokuen_finished_surfaces.py`
- acceptance evidence: Passed 2026-07-27: all nine specialist workbenches plus Home, Apps, Aide, Andromeda, Docs, Files, Settings, setup, Passwords, News, and extension gates passed keyboard, focus return, desktop/phone/200-percent reflow, reduced motion, themes, custom-control, overflow, and clean-console checks.
- external blocks or gaps: none registered

## extension-mobile.pwa-and-extension

Install and operate the PWA and paired extension with explicit offline, background, and permission boundaries.

- triggers: `install PWA`, `exercise offline and reconnect`, `pair and revoke extension`, `test mobile package`
- authority and guards: `install surface and permission boundary`, `paired extension session boundary`
- mutation or side effect: Installs/caches the PWA and pairs, unlocks, matches, fills, locks, or revokes the extension.
- visible states: `ready`, `offline`, `busy`, `error`, `blocked`, `locked`, `recovery`
- success: Offline shell and paired extension boundaries are explicit.
- failure: Unavailable install/device capability remains visible.
- recovery: Reconnect, lock, or revoke removes stale authority.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: Extension controls retain keyboard coverage where rendered.
- control surfaces: none registered
- function surfaces: `install`, `offline-shell`, `background-sync`, `push`, `pair`, `unlock`, `match`, `fill`, `lock`, `revoke`
- automated tests: `tests/test_capacitor_11b.py`, `tests/js/browser_extension_phase9.test.mjs`, `tests/test_manifest_11b.py`
- acceptance evidence: Blocked 2026-07-27: manifest/offline/background contracts and the real unpacked extension pairing/fill/restart/revoke flow pass; final installed-PWA and packaged mobile-device acceptance requires an external install surface or physical/simulated mobile target unavailable here.
- external blocks or gaps: `Installed PWA and packaged mobile acceptance require an external install/device target.`

## backup-recovery.lifecycle

Create encrypted backups, restore safely, update with rollback, uninstall preserving data, and recover interrupted lifecycle work.

- triggers: `fresh macOS install`, `fresh Linux VM install`, `recover interrupted update`, `uninstall preserving data`, `restore and roll back`
- authority and guards: `encrypted backup and recovery key boundary`, `owned install/update targets`, `rollback preflight`
- mutation or side effect: Creates/restores backups and stages, accepts, rolls back, or uninstalls lifecycle state.
- visible states: `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Verified lifecycle work preserves owner data and records recovery state.
- failure: Unknown process, dirty code, or unsafe restore fails closed.
- recovery: Interrupted update and restore flows are resumable/rollback-aware.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; Server owns visible lifecycle controls.
- control surfaces: none registered
- function surfaces: `routes.backup`, `routes.export`, `update`, `restore`, `automatic_backup`, `webdav-backup`, `s3-backup`
- automated tests: `tests/test_automatic_backup.py`, `tests/test_backup_recovery.py`, `tests/test_native_install.py`
- acceptance evidence: Blocked 2026-07-27: fresh macOS native install/uninstall, preserved-data, backup/restore, interrupted-update, and rollback regressions pass on disposable roots; the required fresh Linux VM lifecycle scenario has no disposable VM target in this environment.
- external blocks or gaps: `Fresh Linux VM lifecycle acceptance needs a disposable VM.`

## developer-interfaces.api-cli

Expose scoped API, OpenAI-compatible, shell, code, capability, and CLI interfaces without bypassing owner policy.

- triggers: `issue and revoke API token`, `call OpenAI-compatible API`, `reject scope escalation`, `run CLI tests`
- authority and guards: `scoped token and owner policy`, `CLI safety boundary`
- mutation or side effect: Issues/revokes scoped API tokens and executes permitted CLI/API/shell/code actions.
- visible states: `ready`, `busy`, `error`, `blocked`, `recovery`
- success: Permitted interface output respects the configured scope.
- failure: Scope escalation is rejected.
- recovery: Revoke or reissue through the scoped authority.
- busy and repeat: Shared KOKUEN controls reject re-entry while aria-busy is true; feature-specific exceptions are recorded as gaps.
- keyboard and focus: No dedicated control root is registered; Server/settings surfaces own visible controls.
- control surfaces: none registered
- function surfaces: `routes.capabilities`, `routes.code`, `routes.shell`, `routes.openai_compat`, `test`
- automated tests: `tests/test_api_tokens.py`, `tests/test_api_openai_compat.py`, `tests/test_capabilities.py`, `tests/test_shell_pty.py`, `tests/test_cli_safety.py`
- acceptance evidence: Passed 2026-07-27: scoped-token UI/API, issue/revoke, scope-escalation rejection, OpenAI-compatible route behavior, capability policy, real shell PTY, CLI safety, and native lifecycle command tests pass on isolated data.
- external blocks or gaps: none registered

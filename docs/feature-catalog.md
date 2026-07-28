# Alles feature catalog

Generated from `features/registry.json`. Edit the registry, then run
`python scripts/generate_feature_catalog.py`. Do not hand-edit this file.

## Setup Security

### setup-security.owner-setup

Install, initialize, authenticate, and safely configure one owner without exposing private data.

- app: `setup`
- risk: `critical`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the fresh isolated Phase 9 setup/password browser gate completed first-run setup; setup, auth, server-config, recent-owner, and durable-resume backend regressions passed.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_api_setup.py`, `tests/test_auth.py`, `tests/test_server_config.py`
- real-computer scenarios: `fresh owner setup`, `recent-owner reauthentication`, `resume interrupted setup`
- route owners: `routes.auth`, `routes.setup`, `routes.api_tokens`, `routes.status`
- control roots: `#setup-wizard`
- CLI commands: `install`, `uninstall`, `doctor`
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Home

### home.capture-and-navigation

Capture work, review current context, open the nine workbenches, and receive local notices.

- app: `home`
- risk: `medium`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the isolated Home/Apps gate captured one task, opened all nine workbenches, and passed desktop/phone layout, keyboard, retry, focus, overflow, and clean-console checks.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_home.py`, `tests/test_today_golden.py`, `tests/pw_afterlife_home_apps.py`
- real-computer scenarios: `capture from Home`, `open every workbench`, `use Home at phone width`
- route owners: `app`, `routes.today`, `routes.briefing`, `routes.notify`, `routes.push`, `routes.timeline`
- control roots: `body`, `#app-drawer`, `#today-view`, `#home-view`
- CLI commands: none
- jobs: `day_events`, `reminders`, `calendar_reminders`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Aide

### aide.conversation-and-execution

Run model conversations, projects, memory, research, delegated work, and owner-approved local execution.

- app: `aide`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: local runtime, policy, typed-tool, Full Access, shell, and redacted-audit coverage passes, but completing a real model-backed Auto task requires a disposable configured model provider; no provider credential was supplied.
- platforms: `macos`, `linux`, `web`
- dependencies: `configured model provider`
- Aide tools: `apply_patch`, `bash`, `browse_click`, `browse_open`, `browse_read`, `browse_screenshot`, `browse_type`, `code_symbols`, `computer_click`, `computer_key`, `computer_move`, `computer_scroll`, `computer_type`, `diagnostics`, `edit_file`, `find_definition`, `git_branch`, `git_commit`, `git_diff`, `git_status`, `github_create_issue`, `github_create_pr`, `github_get_file`, `github_get_repo`, `github_list_issues`, `github_list_prs`, `github_list_repos`, `github_me`, `github_search_code`, `github_search_repos`, `glob_files`, `grep_files`, `list_files`, `memory_add`, `memory_search`, `opencode_run`, `read_file`, `recall`, `revert_file`, `screenshot`, `search_code`, `shell`, `skill_list`, `skill_load`, `skill_match`, `spawn_agent`, `spawn_agents`, `todo_update`, `web_fetch`, `web_search`, `write_file`
- automated tests: `tests/test_agent_tools.py`, `tests/test_agent_runtime.py`, `tests/test_policy.py`, `tests/js/aide_afterlife_shell.test.mjs`
- real-computer scenarios: `complete an Auto task`, `arm Full Access`, `inspect a redacted audit`
- route owners: `routes.agent`, `routes.chat`, `routes.sessions`, `routes.models`, `routes.local_models`, `routes.memory`, `routes.research`, `routes.rag`, `routes.textindex`, `routes.images`, `routes.skills`, `routes.delegation`, `routes.personas`, `routes.projects`, `routes.usage`, `routes.insights`, `routes.recall`, `routes.voice`
- control roots: `#chat`, `#project-view`, `#models-view`, `#model-modal`, `#brain-view`, `#reminders-view`, `#aide-scheduled-view`, `#skills-view`, `#usage-view`, `#aide-work-panel`
- CLI commands: none
- jobs: `user_model`, `insights`, `model_refresh`, `personal_reconcile`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

### aide.selectable-questions

Ask one to four durable questions with two to five choices, optional free text, reload/resume, cancellation, and Discord rendering.

- app: `aide`
- risk: `medium`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: typed ask_user, durable agent/Jarvis state, cancellation, pointer, keyboard, free text, reload/reattach, model continuation, and Discord rendering pass focused tests and the real browser gate; answering through a live Discord bot requires disposable bot credentials not supplied.
- platforms: `macos`, `linux`, `web`
- dependencies: `durable Aide runs`
- Aide tools: `ask_user`
- automated tests: `tests/test_aide_questions.py`, `tests/test_agent_runtime.py`, `tests/test_jarvis_records.py`, `tests/test_jarvis_discord.py`, `tests/pw_aide_questions_real.py`
- real-computer scenarios: `answer by pointer`, `answer by keyboard`, `reload and resume`, `answer through Discord`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Andromeda

### andromeda.cited-search

Return fast web results, a compact cited answer, and optional independent freshness-aware verification.

- app: `andromeda`
- risk: `medium`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: live DuckDuckGo search, separated results, decisive snippet emphasis, citations, recovery controls, and honest model-unavailable state passed in Chromium, Safari, and Computer Use; compact answer and independent verifier execution require disposable model credentials.
- platforms: `macos`, `linux`, `web`
- dependencies: `search provider`, `answer model`, `optional verifier model`
- Aide tools: none
- automated tests: `tests/test_andromeda_phase4.py`, `tests/js/andromeda_phase4.test.mjs`, `tests/pw_afterlife_andromeda.py`
- real-computer scenarios: `search and open citations`, `toggle verification`, `render failed checks honestly`
- route owners: `routes.andromeda`, `routes.search`, `routes.compare`
- control roots: `#andromeda-view`, `#compare-view`, `#search-modal`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Plan

### plan.tasks-calendar

Manage tasks, Kanban, calendars, reminders, and countdowns through one workbench.

- app: `plan`
- risk: `medium`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the rendered Plan gate created and moved tasks atomically, exercised keyboard board controls, details/history, desktop/phone/zoom reflow, and a clean console; calendar create/delete is covered by the isolated API and browser regressions.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `calendar_create`, `calendar_delete`, `calendar_list`, `task_add`, `task_done`, `task_list`
- automated tests: `tests/test_task_reorder.py`, `tests/test_api_calendars.py`, `tests/js/plan_board.test.mjs`
- real-computer scenarios: `create and move a task`, `keyboard board navigation`, `create and delete an event`
- route owners: `routes.tasks`, `routes.calendar`, `routes.calendars`, `routes.reminders`, `routes.days`
- control roots: `#plan-view`, `#tasks-view`, `#calendar-view`, `#days-view`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Inbox

### inbox.mail-and-contacts

Read and send mail and manage contacts through owner-configured connectors.

- app: `inbox`
- risk: `high`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: mail, SMTP outbox, contacts, CardDAV, and CalDAV implementations and isolated failure paths pass, but the three real-computer scenarios require a disposable external mailbox and address-book account; none was supplied.
- platforms: `macos`, `linux`, `web`
- dependencies: `optional IMAP/SMTP`, `optional CardDAV/CalDAV`
- Aide tools: `contact_add`, `contact_list`, `mail_list`, `mail_read`, `mail_send`
- automated tests: `tests/test_mail.py`, `tests/test_contact_events.py`, `tests/test_carddav.py`, `tests/test_caldav_sync.py`
- real-computer scenarios: `connect a disposable mailbox`, `send a test message`, `edit a test contact`
- route owners: `routes.mail`, `routes.contacts`, `routes.caldav`, `routes.carddav`
- control roots: `#inbox-view`, `#mail-view`, `#contacts-view`
- CLI commands: none
- jobs: `mail_outbox`, `ics_subscriptions`, `carddav_auto`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Docs

### docs.documents-and-journal

Create, edit, search, link, recover, and migrate documents and journal entries.

- app: `docs`
- risk: `high`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the current Docs home and real Docs gates passed edit/draft/reload/recovery, backlink-safe rename, journal migration rollback, keyboard, responsive, focus, and clean-console checks on isolated data.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `docs_read`, `docs_search`, `docs_write`, `note_append`, `note_backlinks`, `note_list`, `note_read`, `note_search`, `note_write`
- automated tests: `tests/test_notes_vault.py`, `tests/test_vault_md.py`, `tests/test_journal.py`, `tests/test_journal_migration.py`
- real-computer scenarios: `edit and recover a document`, `rename with backlink preservation`, `migrate and roll back a journal entry`
- route owners: `routes.notes`, `routes.journal`, `routes.journal_migration`, `routes.vault_md`
- control roots: `#docs-workbench-view`, `#wiki-view`, `#docs-dialog`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Files Photos

### files-photos.locations-and-media

Browse managed and approved locations, operate safely on files, keep explicit offline copies, and organize photos.

- app: `files`
- risk: `critical`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the real isolated Files gate covered Alles/Connected scopes, local operations, copy/move/rollback, external-vault conflict recovery, offline states, Gallery return Home, keyboard, focus, themes, phone/zoom, and a clean console.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `files_locations_list`, `files_operation_create`, `files_operation_undo`, `files_operations_list`
- automated tests: `tests/test_files_location_identity.py`, `tests/test_storage_locations.py`, `tests/test_file_operations.py`, `tests/test_vault_transfer.py`, `tests/test_vault_transfer_api.py`, `tests/js/files_phase7_real.test.mjs`, `tests/pw_phase7_files_real.py`
- real-computer scenarios: `browse Alles and Connected`, `copy move and roll back`, `open Gallery and return Home`, `resolve a vault conflict`
- route owners: `routes.files`, `routes.file_operations`, `routes.offline_files`, `routes.storage_locations`, `routes.photos`, `routes.gallery`, `routes.uploads`, `routes.shared`
- control roots: `#files-workbench-view`, `#files-view`, `#gallery-view`, `#photos-view`, `#files-preview-modal`, `#files-location-dialog`, `#files-transfer-dialog`
- CLI commands: none
- jobs: `blob_gc`, `clip_index`, `faces_index`, `photo_watch`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Library

### library.reading-and-news

Save reading, manage books, collect cited news, and keep cookbook material.

- app: `library`
- risk: `medium`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the real isolated Library saved and opened example.com, archived it, added/rated/completed a book, and the News gate enabled, ran, cited, and explicitly saved a brief with desktop/phone/zoom and clean-console proof.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `book_add`, `books_list`, `read_list`, `read_save`
- automated tests: `tests/test_books.py`, `tests/test_read.py`, `tests/test_news.py`
- real-computer scenarios: `save and open a page`, `add and update a book`, `deliver a cited news brief`
- route owners: `routes.books`, `routes.read`, `routes.cookbook`, `routes.news`
- control roots: `#library-view`, `#books-view`, `#read-view`, `#cookbook-view`
- CLI commands: none
- jobs: `read_feeds`, `scheduled_news`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Health

### health.logs-and-habits

Record health observations and track habits without presenting the app as medical care.

- app: `health`
- risk: `high`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: isolated Health and habit browser gates logged synthetic data, completed a habit, and checked baseline, anomaly, empty, and partial-summary states without medical claims.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `habit_add`, `habit_log`, `habits_list`, `health_log`, `health_summary`
- automated tests: `tests/test_health.py`, `tests/test_habits.py`
- real-computer scenarios: `log a synthetic measurement`, `complete a habit`, `inspect empty and partial summaries`
- route owners: `routes.health`, `routes.habits`
- control roots: `#health-group-view`, `#health-view`, `#habits-view`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Finance

### finance.actual-ledger

Use Actual Budget as canonical ledger and import statements read-only with provenance and undo.

- app: `finance`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: canonical-authority, statement preview/apply/provenance/conflict/undo, and migration regressions pass, but reconciling a live disposable Actual ledger requires an installed disposable Actual service not available in this acceptance environment.
- platforms: `macos`, `linux`, `web`
- dependencies: `managed or external Actual Budget`
- Aide tools: `money_query`
- automated tests: `tests/test_actual_finance_canonical.py`, `tests/test_finance_imports_phase8.py`, `tests/test_money.py`
- real-computer scenarios: `reconcile a disposable ledger`, `import statement fixtures`, `undo an import`
- route owners: `routes.money`, `routes.finance_actual`, `routes.finance_imports`, `routes.subscriptions`
- control roots: `#finance-view`, `#money-view`, `#subs-view`
- CLI commands: none
- jobs: `holdings_price`, `subscriptions`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

### finance.bank-connectors

Synchronize accounts read-only through SimpleFIN or Plaid with reconnect, revocation, deduplication, and reviewed bank import profiles.

- app: `finance`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: connector cursor/dedupe/consent/reconnect/revoke tests and reviewed Canadian/Chinese import profiles pass; live Plaid/SimpleFIN scenarios require disposable aggregator credentials not supplied. Chinese banks correctly remain statement and owner-authorized notification/email ingestion only.
- platforms: `macos`, `linux`, `web`
- dependencies: `Actual Budget`, `SimpleFIN or Plaid`
- Aide tools: `finance_accounts_list`, `finance_import_profiles`, `finance_transactions_list`
- automated tests: `tests/test_finance_connectors.py`, `tests/test_finance_imports_phase8.py`, `tests/test_money_csv.py`
- real-computer scenarios: `connect Plaid sandbox`, `deduplicate transactions`, `expire and reconnect consent`, `disconnect and revoke`
- route owners: `routes.finance_connections`
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: `simplefin`, `plaid`, `actual-budget`
- PWA functions: none
- extension functions: none

## Passwords

### passwords.vault-and-browser

Store encrypted secrets and fill exact-site credentials through paired short-lived browser sessions without model plaintext.

- app: `passwords`
- risk: `critical`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the real unpacked Chromium extension paired to a disposable vault, filled only the exact local fixture origin, never submitted, rejected broader authority, cleared its short session on restart, locked, and revoked cleanly.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_vault_autofill.py`, `tests/test_browser_passwords.py`, `tests/js/browser_extension_phase9.test.mjs`
- real-computer scenarios: `pair the extension`, `fill an exact test site`, `reject a mismatched origin`, `revoke a browser`
- route owners: `routes.vault`, `routes.browser_passwords`
- control roots: `#vault-workbench-view`, `#vault-view`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: `browser-extension`
- PWA functions: none
- extension functions: none

## Server

### server.adguard-home

Prepare pinned AdGuard Home when supported and activate DNS only after preflight, backup, health checks, and rollback proof.

- app: `server`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: pinned metadata, prepare-without-start, exact listener preflight, encrypted client/API, ownership, typed Aide tools, unavailable-state UI, and rollback tests pass; DNS activation and statistics inspection require a disposable VM or isolated network not available here.
- platforms: `macos`, `linux`
- dependencies: `supported host`, `available DNS ports`, `isolated activation network`
- Aide tools: `adguard_dashboard`, `adguard_filtering_set`, `adguard_rewrite_change`
- automated tests: `tests/test_managed_companions.py`, `tests/test_managed_companion_clients.py`, `tests/test_managed_companion_api.py`, `tests/test_aide_managed_companion_tools.py`, `tests/js/server_workbench_phase12.test.mjs`
- real-computer scenarios: `prepare without activation`, `activate in isolation`, `inspect query statistics`, `roll back DNS`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: `adguard-home`
- PWA functions: none
- extension functions: none

### server.management

Inspect and control owned services, machine health, updates, logs, policy, and watched resources through fail-closed authority.

- app: `server`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: Neofetch/btop, process layout, fail-closed policy editor, unsafe-edit rejection, lifecycle rollback tests, Safari, and Computer Use inspection pass; no registered disposable owned service or disposable update release was available for live restart/rollback.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: `server_companions_list`, `server_service_control`, `server_services_list`, `watch_add`, `watch_status`
- automated tests: `tests/test_api_system.py`, `tests/test_server_policy_phase12.py`, `tests/test_native_install.py`
- real-computer scenarios: `inspect neofetch and btop`, `restart a disposable service`, `reject an unsafe policy edit`, `perform update rollback`
- route owners: `routes.system`, `routes.macos`, `routes.watch`
- control roots: `#server-workbench-view`, `#system-view`, `#watch-view`, `#activity-view`
- CLI commands: `start`, `stop`, `restart`, `status`, `logs`, `open`
- jobs: `watch`
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

### server.nginx-proxy-manager

Prepare pinned Nginx Proxy Manager when Docker prerequisites pass and manage proxy hosts, certificates, access, updates, and rollback.

- app: `server`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: pinned metadata, Docker prerequisite handling, prepare-without-start, encrypted client/API, proxy-host/certificate UI, typed Aide tools, ownership, and rollback tests pass; live proxy activation requires a disposable Docker VM or isolated network not available here.
- platforms: `macos`, `linux`
- dependencies: `Docker`, `available proxy ports`, `isolated activation network`
- Aide tools: `npm_dashboard`, `npm_proxy_host_create`
- automated tests: `tests/test_managed_companions.py`, `tests/test_managed_companion_clients.py`, `tests/test_managed_companion_api.py`, `tests/test_aide_managed_companion_tools.py`, `tests/js/server_workbench_phase12.test.mjs`
- real-computer scenarios: `prepare without Docker`, `activate in isolation`, `create a proxy host`, `roll back service`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: `nginx-proxy-manager`
- PWA functions: none
- extension functions: none

## Integrations

### integrations.model-authentication

Connect model providers through legitimate API keys, supported OAuth, or an owner-managed OpenAI-compatible proxy with exact auth type and revocation guidance.

- app: `settings`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: 64 focused provider/auth/routing tests and the real desktop/phone Settings gate pass API-key/proxy metadata, Kimi/DeepSeek guidance, Gemini PKCE start, encrypted secrets, refresh/revoke, keyboard, overflow, and clean console. Live provider OAuth/API-key connection requires disposable external credentials not supplied.
- platforms: `macos`, `linux`, `web`
- dependencies: `provider credentials or OAuth client registration`
- Aide tools: none
- automated tests: `tests/test_model_auth.py`, `tests/test_model_catalog_migration.py`, `tests/test_model_providers.py`, `tests/test_llm.py`, `tests/pw_model_auth_real.py`
- real-computer scenarios: `connect Gemini OAuth`, `connect and revoke an API key`, `discover CLIProxyAPI models`, `show unsupported OAuth honestly`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: `model_oauth_refresh`
- automation actions: none
- integrations: `gemini-oauth`, `openai-api-key`, `claude-api-key`, `kimi-api-key`, `deepseek-api-key`, `cliproxyapi`
- PWA functions: none
- extension functions: none

### integrations.owner-connectors

Connect Discord, MCP, external endpoints, and signed webhooks with explicit health and revocation.

- app: `settings`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: Discord, MCP, encrypted credential migration, signed webhook, health, and revocation regressions pass; real pairing and delivery require disposable external connector credentials and endpoints that were not supplied.
- platforms: `macos`, `linux`, `web`
- dependencies: `owner-supplied connector credentials`
- Aide tools: `mcp_call_tool`, `mcp_list_tools`
- automated tests: `tests/test_api_mcp.py`, `tests/test_jarvis_discord.py`, `tests/test_mcp_credentials_migration.py`, `tests/test_connections.py`
- real-computer scenarios: `pair a Discord owner`, `connect and revoke MCP`, `test a signed webhook`, `disconnect an endpoint`
- route owners: `routes.connections`, `routes.mcp`, `routes.jarvis`, `routes.webhooks`
- control roots: none
- CLI commands: none
- jobs: `jarvis_scheduler`, `jarvis_outbox`, `jarvis_events`
- automation actions: none
- integrations: `discord-bot`, `mcp`, `webhooks`, `external-openai-compatible`
- PWA functions: none
- extension functions: none

## Automation

### automation.schedules-and-actions

Run durable schedules, chains, proactive work, and explicit automation actions with retry and audit state.

- app: `aide`
- risk: `high`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: the rendered Scheduled screen created and edited schedules with custom controls; automation and Jarvis regressions cover pause/resume, restart recovery, honest failed/uncertain actions, cancellation, retries, and audit history. Direct scheduled navigation is now awaited and the News acceptance gate passes.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_automations.py`, `tests/test_chains.py`, `tests/test_proactive.py`
- real-computer scenarios: `create and pause a schedule`, `resume after restart`, `inspect a failed action`, `cancel a run`
- route owners: `routes.automations`, `routes.chains`, `routes.proactive`
- control roots: none
- CLI commands: none
- jobs: `automations`, `proactive`
- automation actions: `create_note`, `create_task`, `notify`, `notify_digest`, `push`, `push_digest`
- integrations: none
- PWA functions: none
- extension functions: none

## Localization

### localization.credits

Show dependencies, adapted sources, inspirations, revisions, licenses, source links, and required notices.

- app: `settings`
- risk: `high`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: 497 generated records have complete category, revision, license, source, and notice evidence; all required inspirations are distinct, Settings search/detail was exercised with Obsidian, and rendered desktop/phone credits states pass.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_credits_manifest.py`, `scripts/generate_credits.py`
- real-computer scenarios: `search named inspirations`, `open a local notice`, `show unavailable notice honestly`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

### localization.regional-settings

Apply reviewed language catalogs and independent automatic or explicit region, timezone, clock, week, and currency preferences.

- app: `settings`
- risk: `medium`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: unified Settings detected region/timezone automatically, used custom region and format controls, loaded all reviewed catalogs, persisted overrides, and passed the desktop/phone localization gate.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_localization_catalogs.py`, `tests/js/i18n.test.mjs`
- real-computer scenarios: `use automatic region`, `override formats`, `switch reviewed languages`, `restart and preserve choices`
- route owners: `routes.settings`, `routes.appearance`
- control roots: `#settings-modal`
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Accessibility

### accessibility.interface-contract

Keep controls custom, semantic, keyboard-operable, focus-visible, responsive, contrast-safe, and usable with reduced motion and 200 percent zoom.

- app: `all`
- risk: `high`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: all nine specialist workbenches plus Home, Apps, Aide, Andromeda, Docs, Files, Settings, setup, Passwords, News, and extension gates passed keyboard, focus return, desktop/phone/200-percent reflow, reduced motion, themes, custom-control, overflow, and clean-console checks.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_design_system_contract.py`, `tests/pw_kokuen_finished_surfaces.py`
- real-computer scenarios: `complete flows by keyboard`, `verify dialog focus return`, `test responsive and zoom states`, `test reduced motion and themes`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

## Extension Mobile

### extension-mobile.pwa-and-extension

Install and operate the PWA and paired extension with explicit offline, background, and permission boundaries.

- app: `home`
- risk: `high`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: manifest/offline/background contracts and the real unpacked extension pairing/fill/restart/revoke flow pass; final installed-PWA and packaged mobile-device acceptance requires an external install surface or physical/simulated mobile target unavailable here.
- platforms: `macos`, `linux`, `web`
- dependencies: `supported browser`
- Aide tools: none
- automated tests: `tests/test_capacitor_11b.py`, `tests/js/browser_extension_phase9.test.mjs`, `tests/test_manifest_11b.py`
- real-computer scenarios: `install PWA`, `exercise offline and reconnect`, `pair and revoke extension`, `test mobile package`
- route owners: none
- control roots: none
- CLI commands: none
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: `install`, `offline-shell`, `background-sync`, `push`
- extension functions: `pair`, `unlock`, `match`, `fill`, `lock`, `revoke`

## Backup Recovery

### backup-recovery.lifecycle

Create encrypted backups, restore safely, update with rollback, uninstall preserving data, and recover interrupted lifecycle work.

- app: `server`
- risk: `critical`
- implementation: `shipped`
- acceptance: `blocked`
- acceptance evidence: Blocked 2026-07-27: fresh macOS native install/uninstall, preserved-data, backup/restore, interrupted-update, and rollback regressions pass on disposable roots; the required fresh Linux VM lifecycle scenario has no disposable VM target in this environment.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_automatic_backup.py`, `tests/test_backup_recovery.py`, `tests/test_native_install.py`
- real-computer scenarios: `fresh macOS install`, `fresh Linux VM install`, `recover interrupted update`, `uninstall preserving data`, `restore and roll back`
- route owners: `routes.backup`, `routes.export`
- control roots: none
- CLI commands: `update`, `restore`
- jobs: `automatic_backup`
- automation actions: none
- integrations: `webdav-backup`, `s3-backup`
- PWA functions: none
- extension functions: none

## Developer Interfaces

### developer-interfaces.api-cli

Expose scoped API, OpenAI-compatible, shell, code, capability, and CLI interfaces without bypassing owner policy.

- app: `server`
- risk: `critical`
- implementation: `shipped`
- acceptance: `passed`
- acceptance evidence: Passed 2026-07-27: scoped-token UI/API, issue/revoke, scope-escalation rejection, OpenAI-compatible route behavior, capability policy, real shell PTY, CLI safety, and native lifecycle command tests pass on isolated data.
- platforms: `macos`, `linux`, `web`
- dependencies: none
- Aide tools: none
- automated tests: `tests/test_api_tokens.py`, `tests/test_api_openai_compat.py`, `tests/test_capabilities.py`, `tests/test_shell_pty.py`, `tests/test_cli_safety.py`
- real-computer scenarios: `issue and revoke API token`, `call OpenAI-compatible API`, `reject scope escalation`, `run CLI tests`
- route owners: `routes.capabilities`, `routes.code`, `routes.shell`, `routes.openai_compat`
- control roots: none
- CLI commands: `test`
- jobs: none
- automation actions: none
- integrations: none
- PWA functions: none
- extension functions: none

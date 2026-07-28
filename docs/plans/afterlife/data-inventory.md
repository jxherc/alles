# Afterlife Phase 0 - current data and root inventory

- **Status:** code-audited and synthetic-regression-locked; refreshed 2026-07-26
- **Private-content rule:** this inventory comes from code, schemas, and throwaway fixtures. No owner
  database, vault, upload, photo, file, or connector content was read.

## Backup rule

A full backup captures the managed `ALLES_DATA` tree and a consistent online snapshot of `aide.db`.
Photos are off by default because they may be very large. External Files and Photos roots are never
copied silently. The configured Markdown Vault is the deliberate exception: if it is outside
`ALLES_DATA`, backup freezes it into `external-vault/`, rejects concurrent changes, and recovery remaps
it under the restored Alles data root instead of writing to the old external path.

An `ALLES_DB` path outside `ALLES_DATA` is not supported by whole-data recovery. Backup refuses that
configuration rather than quietly omitting the database.

## Manifest root roles

| Manifest role | Source | Current backup policy |
| --- | --- | --- |
| `data` | `ALLES_DATA` | Required and included. |
| `vault` | `settings.vault_dir` | Included in place when inside `ALLES_DATA`; an external Vault is captured into `external-vault/` and restored under the new data root. |
| `files` | `settings.files_dir` | Included only when inside `ALLES_DATA`; an external Files root is explicitly excluded. |
| `photos` | `settings.photos_dir` | Included only when inside `ALLES_DATA` and selected, or when overlap with another included root forces inclusion. |
| `photos_watch` | `settings.photos_watch_folder` | Source-only folder; excluded. Imported copies follow the Photos policy. |
| `agent_allowed_roots` | `settings.agent_allowed_roots` | Permission roots only; contents excluded. |
| `project_workspaces` | `projects.working_dir` | Path metadata is in SQLite; workspace contents are excluded. |
| `photokit_library` | macOS Photos | System library excluded. Imported copies follow the Photos policy. |
| `remote_services` | Mail, CalDAV, CardDAV, MCP, models, search, notifications, and webhooks | Local config/cache is included; the remote service's authoritative copy is excluded. |
| `webdav` | external backup collection | Backup destination only. Remote contents are not copied into an archive; the manifest records `configured` or `not-configured`. |
| `s3` | external S3-compatible bucket | Backup destination only. Remote contents are not copied into an archive; the manifest records `configured` or `not-configured`. |
| `model_cache` | `ALLES_CLIP_DIR`, `ALLES_FACES_DIR`, and repository model caches | Rebuildable and excluded. |
| `codex_home` | `CODEX_HOME` | Separate tool state; excluded. |
| `recovery_work` | sibling `.data-recovery` directory | Staging, exports, journals, and rollback work are excluded to prevent recursive backups. |

## Files storage roots

Phase 7 Storage Locations add three Files root kinds: local, WebDAV, and S3-compatible. Their rows,
encrypted credentials, capabilities, indexes, operations, claims, and offline metadata are included in
the SQLite snapshot. The actual bytes follow these rules:

| Storage kind | Byte policy |
| --- | --- |
| Default local Files root | Follows the `files` manifest role above. |
| Other local Storage Location | External root; path/config metadata is included, but bytes are excluded. |
| WebDAV Storage Location | Remote bytes are excluded. Local verified offline copies and operation state under `ALLES_DATA` are included. |
| S3-compatible Storage Location | Remote objects are excluded. Local verified offline copies and operation state under `ALLES_DATA` are included. |

## Managed on-disk data classes

Unless explicitly excluded below, a data class stored inside `ALLES_DATA` is included by the managed
tree inventory.

| Data class | Current location | Policy |
| --- | --- | --- |
| Primary records | `aide.db` | Required consistent SQLite snapshot; integrity, foreign keys, application ID, and migrations checked. |
| Settings and connector config | `settings.json`, `caldav.json`, `carddav.json`, `webdav_backup.json`, `s3_backup.json`, and SQLite rows | Included when present. Known credentials must be sealed and authenticated for their exact field purpose. |
| Application keys | `secret.key`, `recovery.key`, `vapid.pem` | Included when present and dependency-checked against the exact snapshot. The separately exported recovery key remains owner-held. |
| Passwords | `vaults`, `vault_entries`, WebAuthn rows, and `vault_attachments/*.enc` | Ciphertext included; every attachment row must have its blob. The master password is never stored. |
| Markdown documents | configured Vault root | Included under the Vault rule above, including assets, templates, journal, and note files. |
| Managed Files bytes | configured default Files root | Included only under the Files rule above. Other local and remote Storage Location bytes are excluded. |
| Storage operation state | SQLite operation/claim tables, `storage-transfers/`, `storage-conflicts/`, `.trash/`, and location-scoped receipts | Included when under `ALLES_DATA`; these preserve retry, recovery, ownership, and undo evidence. |
| Offline Files | `offline-files/` plus SQLite rows | Included. These are verified local copies, not a claim that the remote source was backed up. |
| Document safety and migration work | `.document-safety/`, `journal-migrations/`, and Vault transfer state | Included when present so prepared work can be inspected or recovered. |
| Photos | configured Photos root and `.thumbs/` | Uses the Photos opt-in/overlap rule. Photo metadata remains in SQLite. |
| Uploads and legacy Gallery files | `uploads/`, `gallery/` | Included when present. |
| Contact media | `contact_avatars/` | Included when present. |
| Skills | `skills/` | Included when present. |
| Content blobs | `.blobs/` | Included when present. |
| File history and trash | `.versions/`, `.trash/` | Included when present. |
| Agent, Aide, and research state | `agent_runs/`, `agent_shots/`, `research/`, `compare/`, and database run/event rows | Included when present. |
| Managed service definition | `services/searxng/` and `owned-services/` | Compose definition, settings, manifest, rollback definition, and secret are included. Docker images and containers are external rebuildable runtime state. |
| Managed Actual Finance | `services/actual/` | Pinned app, private server authentication, server/client cache, migration exports, cold backups, and app rollback pair are included. The running Node process is external rebuildable runtime state. |
| Sync state | `cal_fires.json`, `photo_sync_state.json` | Included when present. |
| Native helper | `native/` | Included when present, although it can be rebuilt. |
| Indexes and thumbnails | SQLite index rows and managed data folders | Included when present; Photos thumbnails follow the Photos rule. |

## Explicit exclusions

- `aide.db-wal`, `aide.db-shm`, and `aide.db-journal`: replaced by the consistent SQLite snapshot.
- `alles.pid` and `alles-server.log`: runtime-only files.
- Symlinks, junctions, sockets, devices, and other special files: skipped and recorded as warnings.
- External Files, Photos, watch, agent, Project, and additional local Storage Location roots: not copied.
- Full remote mailboxes, calendars, contact books, WebDAV trees, S3 object stores, model providers,
  MCP servers, Discord, Telegram, webhook targets, and push providers: only local state is backed up.
- Docker images, containers, Colima/Docker VM state, model/tool caches, and `CODEX_HOME`: external or
  rebuildable state.
- The WebDAV/S3 backup repositories contain encrypted backup artifacts but are not recursively copied
  into those artifacts.

## SQLite data classes

The current SQLAlchemy inventory contains **120 mapped tables** inside the `aide.db` snapshot.
`schema_migrations` is also included as migration history but is not a SQLAlchemy mapped model.

```text
actual_entity_links, actual_migration_runs, albums, andromeda_saved_searches, andromeda_verification_jobs, api_tokens, attachments, audit_records, automation_attempts,
automation_rules, blobs, booking_pages, browser_connections, books, cached_messages, calendar_events,
calendar_subscriptions, calendars, capability_grant_events, capability_grants, connections,
contact_fields, contact_group_members, contact_groups, contact_links, contacts, cookbook, day_events,
delegated_actions, doc_comments, doc_revisions, event_attendees, faces, file_comments,
file_operation_path_claims, file_operation_source_claims, file_operations, file_tags, file_versions,
finance_connections, finance_import_batches, finance_import_rows, finance_ledger_state, gallery_images, habit_logs, habits,
health_entries, index_chunks, insights, jarvis_connectors,
jarvis_delivery_attempts, jarvis_inbox_events, jarvis_run_events, jarvis_run_prompts, jarvis_runs,
jarvis_triggers, jarvis_workflows, journal_entries, mail_accounts, mail_drafts, mail_rules,
mail_saved_searches, mail_scheduled, mcp_servers, memories, messages, model_endpoints, model_votes,
money_accounts, money_assignments, money_budgets, money_category_rules, money_fx_evidence, money_goals, money_holdings,
money_price_history, money_recurring, money_tag_rules, money_targets, money_transactions,
money_txn_splits, money_watches, monitor_checks, monitors, mutation_events, news_briefs,
news_configuration, news_entries, news_sources, offline_files, people,
persona_docs, personas, photos, proactive_items, proactive_outcomes, proactive_state, projects,
push_subscriptions, read_feeds, read_items, reminders, research_findings, sessions, shares,
signal_snapshots, storage_locations, sub_payments, sub_price_changes, subscriptions, tasks,
tool_chains, trash_items, uploads, vault_attachments, vault_entries, vault_shares, vaults,
webauthn_credentials, webhooks
```

## Fresh evidence

- Runtime enumeration on 2026-07-25 found the 119 mapped table names above and no extra/missing name.
- Synthetic backup tests cover inside/outside roots, the external-Vault freeze/remap path, concurrent
  Vault-change refusal, external `ALLES_DB` refusal, older v1 manifest compatibility, and root policy
  serialization.
- The WebDAV and S3 backup configs are frozen and purpose-bound with the other credential
  dependencies. Synthetic recovery deletes the source install, reconnects to the remote encrypted
  artifact with separately held access, and restores with the separately exported recovery key.
- Phase 7 tests cover local/WebDAV/S3 Storage Location metadata, remote-content exclusion, verified
  offline copies, operation recovery, source/path claims, exact remote identity, and undo safety.
- `tests/test_afterlife_phase0_inventory.py` locks this document's mapped-table and root-role inventory
  to the implementation so later schema/root growth cannot silently leave it stale again.

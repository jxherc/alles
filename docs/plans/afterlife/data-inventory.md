# Afterlife Phase 0 — data and root inventory

- **Status:** implemented; verified with synthetic data only
- **Private-content rule:** this inventory came from code, schemas, and throwaway fixtures. No user vault,
  database, upload, photo, or connector content was read.

## Simple rule

A full backup takes the whole managed `ALLES_DATA` tree, plus a consistent snapshot of `aide.db`.
Photos are off by default because they may be very large. A folder outside `ALLES_DATA` is never copied
silently. The manifest says what was included and what was left out.

An external `ALLES_DB` override is not supported by whole-data recovery. Backup is refused instead of
quietly omitting that database.

## Configured roots

| Manifest role | Source | Current backup policy |
| --- | --- | --- |
| `data` | `ALLES_DATA` | Required and included. |
| `vault` | `settings.vault_dir` | Included only when it is inside `ALLES_DATA`; otherwise explicitly excluded. |
| `files` | `settings.files_dir` | Included only when it is inside `ALLES_DATA`; otherwise explicitly excluded. |
| `photos` | `settings.photos_dir` | Opt-in and included only when it is inside `ALLES_DATA`. |
| `photos_watch` | `settings.photos_watch_folder` | Source-only folder; excluded. Imported copies follow the Photos rule. |
| `agent_allowed_roots` | `settings.agent_allowed_roots` | Permission roots only; contents excluded. |
| `project_workspaces` | `projects.working_dir` | Path metadata is in SQLite; workspace contents are excluded. |
| `photokit_library` | macOS Photos | System library excluded. Imported copies follow the Photos rule. |
| `remote_services` | Mail, CalDAV, CardDAV, MCP, models, search, notifications, webhooks | Local config/cache is included; the remote service's own copy is not. |
| `webdav` | external backup collection | Backup-only destination. Its remote contents are not copied into an archive; the manifest records `configured` or `not-configured`. |
| `s3` | future Files/backup root | Not implemented, so it cannot be labelled backed up. |
| `model_cache` | `ALLES_CLIP_DIR`, `ALLES_FACES_DIR`, repository model cache | Rebuildable and excluded. |
| `codex_home` | `CODEX_HOME` | Separate tool state; excluded. |
| `recovery_work` | sibling `.data-recovery` directory | Staging, exports, and rollback work are excluded to prevent recursive backups. |

## Managed on-disk data classes

| Data class | Current location | Policy |
| --- | --- | --- |
| Primary records | `aide.db` | Required consistent SQLite snapshot; integrity, foreign keys, application ID, and migrations checked. |
| Settings and connector config | `settings.json`, `caldav.json`, `carddav.json`, `webdav_backup.json`, and SQLite rows | Included when present. New backups require every known credential to be sealed and authenticated with its exact field purpose. The WebDAV password uses `backup.webdav.password`; historical plaintext archives remain migration-compatible. |
| Application keys | `secret.key`, `recovery.key`, `vapid.pem` | Frozen into the same temporary snapshot when present. Required keys are authenticated or cross-checked against the exact database and files placed in the archive. |
| Passwords | `vaults`, `vault_entries`, WebAuthn rows, and `vault_attachments/*.enc` | Ciphertext included; every attachment row must have its blob. The master password is never stored. |
| Markdown documents | configured Vault root | Uses the Vault root policy above. Assets, templates, journal, and note files follow the same root. |
| Managed files | configured Files root | Uses the Files root policy above. |
| Photos | configured Photos root and `.thumbs` | Uses the Photos opt-in policy above. Photo metadata remains in SQLite. |
| Uploads and old Gallery files | `uploads/`, `gallery/` | Included when present. |
| Contact media | `contact_avatars/` | Included when present. |
| Skills | `skills/` | Included when present. |
| Content blobs | `.blobs/` | Included when present. |
| File history and trash | `.versions/`, `.trash/` | Included when present. |
| Agent and research history | `agent_runs/`, `agent_shots/`, `research/`, `compare/` | Included when present. |
| Sync state | `cal_fires.json`, `photo_sync_state.json` | Included when present. |
| Native helper | `native/` | Included when present, although it can be rebuilt. |
| Indexes and thumbnails | SQLite index rows and managed data folders | Included when present; Photos thumbnails follow the Photos rule. |

## Explicit exclusions

- `aide.db-wal`, `aide.db-shm`, and `aide.db-journal`: replaced by the consistent SQLite snapshot.
- `alles.pid` and `alles-server.log`: runtime-only files.
- symlinks, junctions, sockets, devices, and other special files: skipped and recorded as warnings.
- external Vault, Files, Photos, watch, agent, and Project folders: never copied without a future explicit
  selection flow.
- full remote mailboxes, calendars, contact books, object stores, model providers, MCP servers, Discord,
  Telegram, webhook targets, and the WebDAV backup collection: Alles backs up its local state, not the
  remote system's authoritative copy. The collection receives only an encrypted backup artifact.

## SQLite data classes

All current SQLAlchemy data tables are inside the `aide.db` snapshot. `schema_migrations` is included too.
The current model inventory is:

```text
albums, api_tokens, attachments, automation_attempts, automation_rules, blobs, booking_pages, books,
cached_messages, calendar_events, calendar_subscriptions, calendars, connections,
contact_fields, contact_group_members, contact_groups, contact_links, contacts, cookbook,
day_events, doc_comments, doc_revisions, event_attendees, faces, file_comments, file_tags,
file_versions, gallery_images, habit_logs, habits, health_entries, index_chunks, insights,
journal_entries, mail_accounts, mail_drafts, mail_rules, mail_saved_searches, mail_scheduled,
mcp_servers, memories, messages, model_endpoints, model_votes, money_accounts,
money_assignments, money_budgets, money_category_rules, money_goals, money_holdings,
money_price_history, money_recurring, money_tag_rules, money_targets, money_transactions,
money_txn_splits, money_watches, monitor_checks, monitors, mutation_events, people,
persona_docs, personas, photos, proactive_items, proactive_outcomes, proactive_state,
projects, push_subscriptions, read_feeds, read_items, reminders, research_findings,
sessions, shares, signal_snapshots, sub_payments, sub_price_changes, subscriptions, tasks,
tool_chains, trash_items, uploads, vault_attachments, vault_entries, vault_shares, vaults,
webauthn_credentials, webhooks
```

## Evidence

- A synthetic backup configures external Vault, Files, Photos, watch, and agent roots and proves none of
  their files enter the archive.
- The manifest records every root role above and the complete data-class policy list.
- A synthetic external `ALLES_DB` override is refused.
- Older format-v1 manifests without the new policy inventory still stage successfully.
- The WebDAV config is frozen with the other credential dependencies, so a mid-backup edit cannot mix
  two credential states.
- A synthetic WebDAV recovery test deletes the source install, reconnects with separately held WebDAV
  access, downloads the remote encrypted artifact, and restores with the separately saved recovery key.

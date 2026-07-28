# architecture

Alles is a single-user FastAPI application backed by SQLite and SQLAlchemy. The browser is vanilla
JavaScript and CSS served directly by `app.py`.

## Authoritative product registry

`features/registry.json` is the machine-readable product and acceptance inventory. Each feature owns its
FastAPI route modules, interactive control roots, CLI commands, registered jobs, automation actions,
integrations, PWA/extension functions, and current Aide tools. `services/feature_registry.py` validates
the schema and rejects ambiguous ownership. `scripts/generate_feature_catalog.py` renders
`docs/feature-catalog.md` and `docs/feature-acceptance-matrix.md`; the reconciliation test compares the
registry with the live application and source registries without reading owner data.

## Phase 7 Files flow

The Files browser calls the storage-location, Files, offline, and operation APIs. Storage services
resolve the selected location to a local, WebDAV, or S3-compatible backend. Durable operations record
progress in SQLite so cancel, retry, restart recovery, and undo survive a browser refresh. Metadata and
search indexing use `location_id + normalized_path`; legacy calls resolve through the default local
location.

## Phase 8 specialist and Finance flow

Phase 8 introduced specialist group overviews over existing APIs. Phase 12 expands that same
`static/js/specialist_groups.js` shell to the nine workbenches documented below. The original app modules
still own their detailed screens, and `static/js/routecompat.js` maps old names and hosts to the matching
group subsection.

Finance first adds exact original/base currency evidence and stable import receipts in SQLite. A
staged migration sends a verified snapshot through `services/actual_bridge.py` to the pinned official
Node bridge. Only a passing reconciliation plus cold backup can switch `finance_ledger_state` to
Actual. Canonical ledger reads and writes then use `services/actual_finance.py`; legacy ledger rows stay
unchanged and read-only. If later staging validation fails, the run records the candidate budget/sync
identity, deletes it through the official client, and verifies absence. A cleanup failure is retained
as `cleanup_required` and must be retried before another stage. Managed Actual data, private
authentication, cache, migration exports, and backups remain under the Alles data root.

## Phase 9 native distribution and setup flow

`services/native_install.py` owns macOS/Linux release directories, private venvs, the dispatcher,
launcher, install manifest, and launchd/systemd-user definition. The current and previous release
pointers move atomically. `cli.py` stages an exact tracked source and its dependencies, probes the
candidate, creates an encrypted data backup, performs the release/data switch, and retains durable
rollback state until acceptance. Uninstall verifies all program/service ownership and keeps personal
data.

`services/setup_state.py` persists five completed-step records in server settings. Basics, Access,
Files, AI/Search, and Protection validate before save, so another browser resumes at the same server
step. Existing Vaults remain untouched; `services/obsidian_setup.py` changes companion files only
after a separate explicit install action. `services/automatic_backup.py` publishes at most one daily
encrypted artifact outside Alles data and prunes only owned artifacts beyond seven.

## Phase 9 Passwords browser flow

`BrowserConnection` stores a browser name, exact extension origin, timestamps, and only the hash of a
narrow persistent device secret. `services/browser_passwords.py` keeps pairing, unlock requests,
five-minute vault sessions, and decrypted vault passwords in process memory. The extension keeps the
device secret in local storage but the fill session only in session storage. Matching compares exact
normalized scheme, IDNA host, and effective port; metadata is returned first and only one still-
matching selected entry is released. Lock/revoke clears server authority immediately. Browser or
server restart clears one side of the short session, so pairing must be unlocked again.

## Phase 10 localization and Credits

`services/localization.py` validates the eight reviewed local catalogs, canonical source revision,
keys, placeholders, plural categories, and explicit core-flow/source-language boundaries. Settings
persists language, region, timezone, clock, week, and currency independently; `static/js/i18n.js`
applies the reviewed locale and shared format choices, while Task/Calendar dispatch deterministic
local input through `services/localized_input.py`. Automatic region/timezone remain empty in server
settings and resolve from each browser.

`services/credits.py` validates `credits/manifest.json`, confines local text paths to the repository,
loads present license/notice files lazily, and returns validated metadata. The Settings Credits pane
consumes only that API. `scripts/generate_credits.py` owns the complete 432-entry inventory and exact
465-file release notice set used by native and container packaging checks.

## Phase 12 workbenches, search verification, and Server policy

`static/js/specialist_groups.js` now owns nine canonical workbench shells: Plan, Inbox, Docs, Files,
Library, Health, Finance, Vault, and Server. It composes overview data from existing APIs and mounts the
existing detailed app roots into subsection slots. `static/js/routecompat.js` and
`static/js/subdomain.js` retain legacy hosts and identifiers as routes to the matching subsection, so
consolidation does not rewrite owner records.

Andromeda starts provider search, answer generation, and optional verification as independent work. The
answer path streams a bounded cited response; `services/andromeda_verifier.py` owns durable verification
jobs and server-validated claim verdicts. Saved searches retain model identities, citations, checked dates,
and corrections so an old check is not presented as current.

Server composes the existing system, service, SearXNG, backup, update, audit, Activity, and Watch paths.
`services/server_policy.py` is the sole authority for `${ALLES_DATA}/server-policy.json`; it validates the
closed schema, file identity and permissions, uses atomic owner-only writes, and defaults to `owned_only`.
The browser editor in `static/js/server_workbench.js` is bound to that API and cannot select another file
or submit a command. `static/js/system.js` remains the one neofetch/btop renderer used by Overview.

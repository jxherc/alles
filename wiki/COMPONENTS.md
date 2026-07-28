# components

## Authoritative feature registry

Location: `features/registry.json`, `services/feature_registry.py`,
`scripts/generate_feature_catalog.py`, and `tests/test_feature_registry.py`.

Purpose: map product behavior to every runtime owner and verification scenario, reject unmapped or
ambiguous additions, generate readable evidence documents, and preserve honest implementation and
acceptance states.

## Storage Locations

Location: `services/storage_locations.py`, `routes/storage_locations.py`.

Purpose: manage local, WebDAV, and S3-compatible roots with read-only or managed access while keeping
credentials sealed.

## Durable file operations

Location: `services/file_operations.py`, `routes/file_operations.py`.

Purpose: queue copy, move, rename, delete, restore, retry, cancel, and undo with restart-safe progress.

## Offline files

Location: `services/offline_files.py`, `routes/offline_files.py`.

Purpose: manage explicit offline cache state under the Alles data root without presenting it as backup.

## Files workbench

Location: `static/js/filesphase7.js`, the `#files-view` markup in `static/index.html`, and scoped styles
in `static/kokuen.css`.

Purpose: provide multi-location browsing, selection, transfers, details, and location management with
custom KOKUEN controls.

## Specialist workbenches

Location: `static/js/specialist_groups.js`, the group sections in `static/index.html`, scoped rules in
`static/kokuen.css`, and compatibility entries in `static/js/routecompat.js`.

Purpose: compose the nine canonical Plan, Inbox, Docs, Files, Library, Health, Finance, Vault, and Server
workbenches over existing specialist APIs while keeping their records, mutation authorities, detailed
screens, and legacy subsection routes intact.

## Andromeda answer and verifier

Location: `static/js/andromeda.js`, `routes/andromeda.py`, `services/andromeda.py`, and
`services/andromeda_verifier.py`.

Purpose: render ordinary search results independently from a compact cited answer, run optional
freshness-sensitive verification as a separate confirmed job, validate claim evidence server-side, and
preserve honest checked/corrected/failure state in saved searches.

## Server management and policy

Location: `static/js/server_workbench.js`, `static/js/system.js`, `routes/system.py`,
`services/server_policy.py`, `services/service_manager.py`, and related backup/update services.

Purpose: compose owned service, search/model, backup, update, log, activity, watch, and policy controls;
reuse the original neofetch/btop monitor; and restrict optional host management to an exact fail-closed
policy schema rather than arbitrary commands or files.

## Managed Actual Finance

Location: `integrations/actual/`, `services/managed_actual.py`, `services/actual_migration.py`,
`services/actual_finance.py`, `routes/finance_actual.py`, and `routes/finance_imports.py`.

Purpose: install the exact reviewed Actual runtime, stage and reconcile an Alles snapshot, back up and
restore managed data, switch ledger authority without dual writes, and keep import/currency evidence
in auditable Alles sidecars. Failed staging validation removes its identified candidate budget and
blocks a new stage when absence cannot be verified.

## Native install and update

Location: `services/native_install.py`, `cli.py`.

Purpose: build and own versioned macOS/Linux releases, private venvs, launchers and user services;
stage exact updates with encrypted paired data rollback; and remove only verified program files.

## First-run setup

Location: `services/setup_state.py`, `services/obsidian_setup.py`, `routes/setup.py`, and
`static/js/setupwizard.js`.

Purpose: validate and persist the five setup steps on the server, resume across browsers, keep
existing Vaults unchanged, and make Obsidian companion installation a separate explicit choice.

## Automatic local backup

Location: `services/automatic_backup.py` and the registered job in `services/jobs.py`.

Purpose: create at most one encrypted backup per day outside Alles data and retain only the newest
seven Alles-owned artifacts.

## Paired browser Passwords access

Location: `services/browser_passwords.py`, `routes/browser_passwords.py`, `extension/`, and the
Connected browsers section in `static/js/vault.js`.

Purpose: pair and revoke named browsers, approve short in-memory unlocks, return exact-site metadata,
release one selected credential, and fill only a safe top-level form without submitting.

## Localization runtime and Settings

Location: `services/localization.py`, `routes/settings.py`, `static/js/i18n.js`, the language pane in
`static/index.html`, and its controller/styles in `static/js/settings.js` and `static/kokuen.css`.

Purpose: validate and load eight reviewed local catalogs, expose canonical review state, persist
independent regional preferences, apply shared formatting, and support deterministic localized Task
and Calendar input without translating owner content.

## Credits manifest and Settings view

Location: `credits/manifest.json`, `services/credits.py`, `routes/settings.py`, and the About & Credits
pane in `static/index.html` and `static/js/settings.js`.

Purpose: validate the complete credit inventory and confined local text paths, generate exact
acknowledgments/notices/licenses, prove package parity, and render a searchable read-only Credits
surface with lazy local text.

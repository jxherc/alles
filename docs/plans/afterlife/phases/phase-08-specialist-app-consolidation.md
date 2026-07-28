# Afterlife Phase 8 - specialist app consolidation

- **Status:** delivered and verified 2026-07-20
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** [`phase-07-files-storage.md`](phase-07-files-storage.md) delivered and verified
- **Design review:** [`../phase-08-design-review.md`](../phase-08-design-review.md)
- **Actual spike:** [`../phase-08-actual-spike.md`](../phase-08-actual-spike.md)
- **Bank report:** [`../phase-08-bank-connections.md`](../phase-08-bank-connections.md)
- **Checkbox rule:** `[x]` means implemented and freshly tested with throwaway data.

## Goal

Compose related specialist work into Plan, Inbox, Library, Health, and Finance without changing owner
records merely because navigation changes. Make Actual Budget the one Finance ledger only after an
additive, reversible parity and cutover gate.

## 8A - low-risk composition

- [x] Map every current specialist view, table, API, compatibility route, and primary browser module.
- [x] Review and record one coherent KOKUEN direction for the five groups.
- [x] Build standalone fake-data Plan, Inbox, Library, Health, and Finance starters.
- [x] Browser-check every starter on desktop/mobile, keyboard, reduced motion, 200 percent zoom, both
  themes, overflow, custom controls, error states, and clean console output.
- [x] Receive explicit owner approval for the exact starters before changing the real interfaces.
- [x] Compose Plan from Calendar, Tasks, and Reminders while preserving their tables and APIs.
- [x] Compose Inbox from Mail and Contacts while keeping their records separate.
- [x] Compose Library from Books, Read, and explicitly saved News.
- [x] Compose Health from health logs and habits without changing sensitive context rules.
- [x] Preserve old hosts, views, deep links, and requested subsections through compatibility routing.

## 8B - Finance schema and parity

- [x] Add original/base currency, deterministic conversion evidence, and stable import identity with an
  additive migration.
- [x] Backfill without changing stored amounts, balances, subscription prices, due dates, or payment
  history.
- [x] Compare old/new account balances and aggregate totals before any Finance read switch.
- [x] Prove a second migration run changes nothing.

**8B gate:** old and new calculations match, original values stay exact, and backfill is idempotent.

## 8C - Finance interface and imports

- [x] Produce the current CIBC and China Merchants Bank official/provider connection report.
- [x] Compose Money and Subscriptions only after 8B parity passes.
- [x] Add reviewed statement and notification profiles according to the report.
- [x] Add preview, stable duplicate detection, conflict handling, receipts, and import-owned undo.
- [x] Expose a bank provider only after the exact account and current privacy/cost boundary is proven.
  No direct provider is currently exposed because neither owner account has passed that gate.

## 8D - Actual core and canonical cutover

- [x] Prove the pinned official Node API, loopback sync-server lifecycle, stable import identity,
  synchronization, cold backup copy, restored-server start, and fresh-client read-back on synthetic
  throwaway data.
- [x] Add the locked Node dependencies and a bounded Alles-owned bridge with structured errors,
  timeouts, secret redaction, and clean shutdown.
- [x] Add managed Actual install, health, start, stop, restart, update, rollback, backup, and restore.
- [x] Map and reconcile accounts, transactions, transfer pairs, payees, categories, budgets, schedules,
  source-currency evidence, and subscription links.
- [x] Migrate synthetic and upgraded Alles ledgers and compare every count, balance, and aggregate.
- [x] Switch transaction writes in one staged cutover without dual-writing.
- [x] Keep old Alles ledger rows read-only for one stable release and require a later fresh backup plus
  owner confirmation before removal.
- [x] Roll back to the unchanged Alles ledger after any failed cutover or restore gate.

## Verification gate

Phase 8 is delivered only when grouping navigation changes no specialist records; repeat imports create
no duplicates; import undo removes only owned rows; and Actual cutover preserves accounts,
transactions, transfers, categories, payees, budgets, schedules, currency evidence, subscription links,
backup/restore, and totals. Full Python, JavaScript, migration, desktop/mobile browser, keyboard,
reduced-motion, theme, overflow, and lint/format gates must use throwaway data.

- [x] Focused 8A browser and compatibility gate passes.
- [x] 8B migration, old/new parity, and second-run gate passes.
- [x] 8C import duplicate, conflict, preview, and undo gate passes.
- [x] 8D synthetic/upgraded migration, cutover, rollback, backup, and restore gate passes.
- [x] Full Python and JavaScript suites pass.
- [x] Ruff lint/format and diff integrity pass.
- [x] Requirement-by-requirement audit records honest checked and unchecked status.

The owner removed autoreview from this delivery scope on 2026-07-20. No clean-autoreview claim is
made or required by this final status.

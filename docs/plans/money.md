# Phase 9 — money (`money.js` + `routes/money.py`) — "the big one"

## Audit (2026-06-18)

Seeded 2 accounts + 7 transactions + 2 budgets and drove the UI (money.localhost, 0 console errors).

Verified working (DO NOT rebuild): accounts CRUD with kinds/opening/archive/colors + computed live
balance; transactions CRUD + inline edit, filter by account/month/category, income/expense sign; CSV
export (spreadsheet-formula-injection safe) + CSV import (dedupes on date+amount+payee); budgets
(monthly per-category caps, spent-vs-limit bars); summary cards (net worth, income, expense, net);
spending-by-category chart; 6-month income/expense trend; month prev/next nav.

Genuine gaps vs a full personal-finance app (none of these exist today):

1. **Transfers between accounts.** Moving money between your own accounts has to be entered as two
   unrelated txns today, which double-counts as both income and expense and pollutes category spend.
2. **Recurring transactions.** No way to auto-post rent/salary/etc. on a schedule (subs has this for
   subscriptions; money has nothing).
3. **Auto-categorization rules.** Imported/typed txns with no category stay "uncategorized"; no
   payee→category rule engine to fix that automatically.
4. **Transaction search + amount range.** You can only filter by *exact* category/account/month — no
   text search across payee/notes and no "transactions over $X".

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **money-1 Transfers between accounts.** `transfer_id` column links the two legs; POST
  `/api/money/transfer` writes a -amount leg on the source + a +amount leg on the destination (both
  category "transfer", shared transfer_id); summary EXCLUDES transfer legs from income/expense/by-
  category (net worth unaffected, balances move); DELETE `/api/money/transfer/{tid}` removes both legs.
  *Why: a transfer primitive is core; without it inter-account moves corrupt every spending number.*
- **money-2 Recurring transactions.** `RecurringTxn` table (account, amount, category, payee, notes,
  cycle, next_date, active, last_posted) + cycle-correct advance + auto-post of every due occurrence up
  to today (idempotent) on load + CRUD + UI section. *Why: rent/salary/loan payments are the backbone
  of a real ledger.*
- **money-3 Auto-categorization rules.** `CategoryRule` table (case-insensitive payee substring →
  category) applied on create + import when category is blank; POST `/api/money/rules/apply` bulk-
  recategorizes existing uncategorized txns; rules CRUD + UI. *Why: turns a messy bank import into a
  categorized ledger without hand-tagging every row.*
- **money-4 Transaction search + amount range + month URL.** GET `/api/money/transactions/search`
  (q over payee/category/notes ci, min/max on |amount|, account, month, date-desc) + a search box in the
  transactions section; reflect the selected month in the URL (`?m=YYYY-MM`) so refresh/deep-link
  restores it (global routing rule). *Why: "what did I spend at X" / "show charges over $100" isn't
  answerable today.*

## Out of scope

Bank/Plaid live sync, multi-currency FX conversion, investment lot tracking, double-entry accounting,
tax reports, shared/household ledgers.

# 4a audit — money: transaction depth

Mapped the money app (16-point sweep) and probed `:8829` live. Money view loads with **0 console
errors** (`audit-money.png`).

## What exists (relevant baseline)
- `Transaction(money_transactions)`: id, account_id, date, amount (signed: + income / − expense),
  category, payee, notes, transfer_id, created_at. No tags/receipt/cleared/split.
- `GET /api/money/summary?month=` buckets expense by the txn's single `category`, excludes transfers
  via `transfer_id`. Budgets read `by_cat[category]`.
- `POST/PATCH /api/money/transactions` — PATCH whitelist is
  `account_id,date,amount,category,payee,notes` (no tags/receipt/cleared).
- `routes/uploads.py` — generic `POST /api/uploads` (stores `{uuid}{ext}` under `data/uploads`,
  Upload row) + `GET /api/uploads/{id}` to serve. Reusable for receipts.

## Gaps (all net-new, confirmed 404)
1. **Splits** — `GET /api/money/transactions/{tid}/splits` → 404. One charge can't span categories.
2. **Tags** — no tags column / filter on transactions.
3. **Receipts** — no way to attach a receipt image to a transaction.
4. **Cleared / reconcile** — no `cleared` flag; `GET /api/money/accounts/{aid}/reconcile` → 404.

## Plan (docs/plans/4a.md)
- **4a-1 backend**: `TxnSplit` model + `tags`/`receipt_id`/`cleared` columns; splits GET/PUT;
  summary distributes split categories (remainder → txn's own category); tag normalize + filter;
  PATCH accepts tags/receipt_id/cleared; reconcile endpoint (cleared balance vs statement). ≥8 unittest.
- **4a-2 frontend**: per-row split editor; tag chips + tag filter; receipt upload (reuses
  `/api/uploads`) + thumbnail/link; cleared checkbox; account reconcile panel. ≥8 pw.

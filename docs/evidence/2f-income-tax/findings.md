# stage 2f - sub bundle/overlap detection + income smoothing & tax planning - audit (2026-06-23)

## current state
- **sub duplicates exist**: `/subscriptions/duplicates` (routes/subscriptions.py:331) union-finds subs
  with the SAME normalized name OR same url host. catches "Netflix" tracked twice. exercised: two
  "Netflix" rows -> one group. solid for exact dupes.
- **no overlap/redundancy detection**: paying for Spotify AND Apple Music (both music, different names +
  hosts) is NOT flagged - they aren't duplicates, they're a redundant overlap. same for two cloud
  drives, two password managers, etc. the plan's "overlap warnings" is genuinely missing.
- **income is invisible**: income txns (amount > 0) are summed into net worth but never CLASSIFIED
  (salary vs freelance vs investment), never rolling-averaged, and there is no quarterly estimated-tax
  organizer. `forecast.category_averages` explicitly EXCLUDES income. exercised: grep'd - no income-type
  or quarterly/tax logic anywhere.

## the gap (2 pieces)
1. **subscription overlap warnings**: a service-category map (music/video/cloud/etc.) + flag when 2+
   active subs share a redundant category. distinct from exact duplicates.
2. **income smoothing + quarterly tax planning** (organize, NOT compute liability):
   - classify income txns by type from the payee (salary/freelance/investment/refund/other).
   - rolling average monthly income over N months.
   - current US estimated-tax quarter + a set-aside suggestion (quarter income x a user rate).
   - a gated quarterly reminder signal as the due date nears.

## fix
- new `services/sub_overlap.py`: `SERVICE_CATEGORY` map + `_service_cat(name)` + `overlaps(subs)` ->
  groups of 2+ active subs in the same redundant category. endpoint `/subscriptions/overlaps`.
- new `services/income.py`: `classify(payee)`, `by_type(db, month)`, `rolling_income(db, months, as_of)`,
  `current_quarter(as_of)` (label/start/end/due), `quarter_income(db, as_of)`, `set_aside(db, as_of, rate)`.
- `signals._accounts` appends a gated quarterly tax reminder (ride the "account" family, like 2c rode
  "budget"); settings `tax_reminders` (off) + `tax_setaside_rate` (0.25). endpoint /money/income/summary.

deterministic, fully testable. no network/LLM.

# stage 2e - tag rules + smart categorization + hierarchy - audit findings (2026-06-23)

## current state
- **category rules work**: `CategoryRule` (payee substring -> category) + `_categorize` auto-fill on
  create_txn (money.py:317), CSV import (475), OFX ingest (521), bulk `/rules/apply` (775). solid.
- **tags are dumb**: `Transaction.tags` is a free csv, normalized by `_norm_tags`. NOTHING auto-applies
  tags - the user types every tag by hand on every txn. exercised: imported a CSV, tags came in empty
  regardless of payee.
- **no hierarchy**: a tag "food/coffee" is just an opaque string. filtering by "food" misses it; there
  is no parent rollup.
- **budgets are category-only**: `Budget` caps spend per category. you cannot budget a tag (e.g. cap all
  "food" spend across groceries+coffee+dining).

## the gap (3 pieces)
1. **tag rules**: a `TagRule` (payee substring -> tag(s)) that auto-applies on create + import, exactly
   like CategoryRule does for category. plus CRUD + a bulk back-fill endpoint.
2. **tag hierarchy**: "food/coffee" should imply ancestor "food" for filtering + rollup.
3. **tag budgeting**: let a `Budget` target a tag; evaluate it against hierarchy-rolled tag spend so a
   "food/coffee" txn counts toward a "food" budget.

## fix
- new `services/tag_rules.py` (pure): `apply_rules(payee, rules, existing)` merges matched tags into
  existing (reuses the _norm_tags csv discipline); `ancestors(tag)` / `expand(csv)` for hierarchy;
  `spending_by_tag(db, month)` rolls expense up per tag honoring ancestors.
- `TagRule` model (new table -> create_all, no migration). wire `apply_rules` into create_txn + CSV +
  OFX alongside `_categorize`. CRUD at /tag-rules + bulk /tag-rules/apply.
- `Budget.tag` nullable column (migration m0003 for existing DBs). `/budgets` upsert/list accept a tag;
  `signals._budget` evaluates tag budgets against `spending_by_tag` (ride the existing budget family).

deterministic, fully testable. the network/LLM is not involved.

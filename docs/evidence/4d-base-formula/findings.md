# stage 4d - docs/notes Base depth - audit findings (2026-06-23)

## current state
- the "Base" (folder-as-database over vault notes) already has: `base_view` (sort), `base-cell` edit,
  `base-rollup` (count/agg over relations), inline `query-block`, and saved views. sorting + rollups +
  relations are DONE.
- what's missing: **formula / computed fields**. you cannot define a column whose value is computed
  from other fields ("{price} * {qty}", "{done} ? 'shipped' : 'open'"). grep confirms no formula engine.

## scope (highest-value testable core)
a safe formula evaluator for Base computed fields. DEFERRED: advanced filter-builder UI (query-block +
saved views already cover spec-based filtering), canvas backlink clustering, threaded comments/@mentions
(frontend + new models) - separate follow-ons.

## fix - new `services/base_formula.py`
- `evaluate(formula, row)` over a restricted Python AST: {field} references resolved from the row;
  allowed = numbers, strings, +-*/% , comparisons, and/or/not, ternary (a if c else b), and a whitelist
  of functions (round/abs/min/max/len/int/float/str/upper/lower). EVERYTHING else (attribute access,
  calls to non-whitelisted names, __import__, comprehensions) is rejected -> safe to run on user input.
- numeric coercion of field values; missing field -> 0/"" ; div-by-zero + bad expr -> {"error": ...}.
- route POST /base-formula {formula, folder} -> evaluate across the folder's base_view rows.

tested: arithmetic + precedence, multiply fields, comparison bool, ternary, string concat, round(),
missing field default, div-by-zero safe, malicious __import__/attribute rejected, len/upper helpers.

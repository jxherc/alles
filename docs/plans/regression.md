# Phase 15 — final full-app regression

## Sweep (2026-06-18)

Booted the isolated server (`:8799`, ALLES_DATA) with real seeded data across every app and ran three
layers of regression:

1. **Full unittest suite** — 957 tests pass (1 skipped). Existing ~512 + all tasks added this run.
2. **Broad load sweep** (`pw_sweep.py`) — all 15 subdomains load with zero real console errors
   (`ERR_CONNECTION_CLOSED`/`ERR_ABORTED`/`ERR_NETWORK_CHANGED` are page-teardown/proxy artifacts, filtered;
   confirmed non-reproducible in isolation).
3. **Deep interaction sweep** (`pw_final.py`) — 25 control/render checks across money, journal, files,
   subs, activity, days, contacts, tasks, calendar, docs, gallery, mail. All pass:
   - money: 4 summary cards, all 5+ sections, txn search box
   - journal: editor, 365-cell year heatmap, mood trend bars
   - files: 4 smart folders, 3-way sort bar
   - subs: tracked rows; activity: feed + summary strip + search; days: cards
   - every app: zero console errors

## Result

No UI/UX bug surfaced in the final sweep — every app's controls render and work end-to-end with seeded
data, zero console errors. Phase 15 therefore added no new bug-tasks. The gate is clean.

## Phases delivered this run (branch `autorun`)

1 docs · 2 mail · 3 calendar · 4 tasks · 5 gallery · 6 contacts · 7 secrets · 8 subscriptions ·
9 money · 10 journal · 11 activity · 12 files · 13 days · 14 aide · 15 regression.
Each phase: audit-first → TDD tasks (≥8 cases, RED→GREEN) → ruff + node lint gate → per-task commit →
per-phase regression sweep. `system` untouched. Realtime full-duplex voice + screen share documented as
deferred (needs a realtime provider; building a non-functional shell would violate the no-fake rule).

---

# 11d — standing regression procedure

The checks to run after any change, in order. All must be green before a microversion is "done".

## 1. Unit + integration suite
```bash
python -m unittest discover -s tests
```
Real FastAPI (Starlette TestClient) over in-memory SQLite. As of 11d: **2195 tests**, every
`tests/test_*.py` module at **≥8 cases**. Watch for cross-test contamination — a test that mutates
a module global (e.g. `services/fx.RATES`) must save/restore it or mock the source (see
`tests/test_fx.py::test_refresh_*`, which earlier leaked live ECB rates into the net-worth tests).
Bisect a suspected pair by running it in order: `python -m unittest tests.test_fx tests.test_money_goals`.

## 2. Lint (touched files only)
```bash
python -m ruff check tests/<changed> --output-format=concise
python -m ruff format --check tests/<changed>
```
Pre-existing errors in files you didn't touch are out of scope (confirm with
`git diff --quiet HEAD -- <file>`). `E712` is intentionally off (SQLAlchemy `== True`).

## 3. JS syntax (touched modules)
```bash
node --check static/js/<file>.js   # and static/sw.js
```

## 4. Broad Playwright sweep — every subdomain loads clean
```bash
ALLES_DATA=.tmp PORT=8800 AUTH_ENABLED=false python app.py &
python tests/pw_regression.py 8800 docs/evidence/<ver>/regression
```
Loads all 16 hosts (apex + aide + 14 apps), 0 real console errors, screenshots each. The `system`
monitor polls forever — use `domcontentloaded` + a `wait_for_selector`, never `networkidle`.

## 5. Deep Playwright sweep — real interactions (capstone)
```bash
python tests/pw_unify_11c.py     # 16-host scope + SSO cross-jump
python tests/pw_final_11d.py     # settings modal, add task, today-doc, quick event, journal, cross-nav
```
Both assert 0 real console errors. IGNORE filters expected transport noise (`net::`, `ERR_`,
`401/403`, `Failed to load resource`).

## Isolation rules
- Never point a test at a real `data/` — always `ALLES_DATA=<tmpdir>` + a throwaway `PORT`.
- Config-touching unit tests: `mock.patch.object(core.settings, "_SETTINGS_FILE", <tempfile>)`.
- Vault/secrets tests: `POST /api/vault/unlock` for the `X-Vault-Token` header.
- Kill the server + `rm -rf .tmp*` when done.

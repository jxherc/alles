# 11d — Test hardening: per-module ≥8-test backlog + final regression

ROADMAP 11d (M, final microversion). Acceptance: `python -m unittest discover -s tests` green;
broad + deep Playwright sweeps pass with 0 real console errors.

## 11d-1 — backlog to ≥8 cases (every module)
Audit at the start of 11d found **66** `tests/test_*.py` modules below the repo's ≥8-case bar
(some as low as 1). Brought **all 66** up to ≥8 with genuine tests — error paths, edge/boundary
cases, alternate inputs, fallback branches — no filler, no stubs, no skips. Done with parallel
sonnet subagents in batches (A–K), each instructed to read the module under test, add real
coverage, run to green, and ruff-clean its files; I verified the aggregate.

Highlights of what got covered: docx/markdown conversion edges, youtube id parsing, fx convert
+ refresh, agent path-guard/intents/sources, money transfers/reconcile, api token/upload/usage,
caldav round-trip, mcp presets, openai-compat aggregation, webpush JWT/encryption, doctor checks,
llm provider detection + the 4-event stream normalizers, pwtools luhn/totp/watchtower, etc.

**Bugs found & fixed during hardening:**
- `tests/test_fx.py::test_refresh_does_not_raise` called the **real** `fx.refresh()`, which on a
  live network does `RATES.clear()` + refills from the ECB feed — leaking live rates into the
  later net-worth tests (`test_money_goals` saw 214.67 ≠ 208.70). Rewrote it to mock `urlopen`
  (one dead-network → False/no-mutation case, one fake-feed → parse+rebase case) and restore
  `RATES`. No more cross-test contamination.
- `test_stt_local` had 3 `skipTest`s that fired because faster_whisper is installed — replaced
  with a deterministic ImportError-mock of the not-installed branch (0 skipped).
- Cleaned up leftover I001/F401/F841 in backlog files from interrupted subagents.

Result: **2195 tests, OK (skipped=1)** — up from 1727 at the end of 11c (+468). Every test module
now ≥8 cases. Pre-existing lint in untouched files (test_crypto/journal/research/…) left as
out-of-scope per repo policy (confirmed unchanged vs HEAD).

## 11d-2 — final deep sweep (tests/pw_final_11d.py — 9/9)
Beyond pw_regression's load-each-host: drives real interactions across the ecosystem —
open+close the aide settings modal, add a task and see it land in the list, open today's daily
doc into the CodeMirror editor, quick-add a natural-language calendar event, render the journal,
and cross-navigate hub→app via a home tile — all with **0 real console errors**. Plus
`docs/plans/regression.md` now documents the standing 5-step regression procedure.

## Final regression
- `python -m unittest discover -s tests` → **Ran 2195 tests, OK**.
- `tests/pw_regression.py 8881` (16 hosts) → **ALL CLEAN**, 0 errors.
- `tests/pw_unify_11c.py` (16-host scope + SSO) → 10/10.
- `tests/pw_final_11d.py` (deep interactions) → 9/9.

## Gate
`python check_progress.py` → **ALL DONE — 178 task(s) complete** (exit 0). The ROADMAP is complete.

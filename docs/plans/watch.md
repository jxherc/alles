# watch — uptime / status dashboard (next-version workstream 1)

Headline feature of the next version. Monitors EXTERNAL things (sites, `/health` endpoints, TLS certs)
— distinct from the `system` app, which watches this machine. Runs on alles' existing infra: the
`jobs` registry polls, SQLite stores a rolling history, FastAPI serves it, vanilla-JS renders it.

## Tasks

### watch-1 — backend (models + route + job) · TDD
- `Monitor` + `MonitorCheck` models in `core/database.py` (`MonitorCheck.id` = int rowid for
  deterministic newest-first ordering).
- `routes/watch.py`: pure helpers `check_passes` / `cert_days_left` / `uptime_pct` / `record_check`
  (prunes to 200/monitor); network probes `perform_check` / `_check_cert` (best-effort, never raise);
  CRUD + `GET /watch/overview` (status + uptime 24h/7d + latency spark) + `GET /watch/{id}/history` +
  `POST /watch/{id}/check`.
- Background job `run_checks()` registered in `app.py` (`jobs.register("watch", …, 60)`); emits
  `watch.down` on a fresh failure. Router wired via `include_router`.
- AI-cost card reuses existing `/api/usage/summary` (no new tracking).
- **Tests** (`tests/test_watch.py`, 25): check_passes status/keyword/latency rules, cert-days,
  uptime %, record/prune, CRUD, overview shape+status, history order, manual-check records failure.

### watch-2 — frontend (module + wiring + audit)
- `static/js/watch.js`: live dashboard (status cards, SVG sparklines, cert expiry-bar, AI card,
  inline add/edit, check-now, refresh-all, 15s poll). Custom controls only.
- Wiring: `subdomain.js` (`watch` host), `app.js` (`_VIEW_IDS`, `showWatchView`, `navigateTo`, `_ICON.watch`,
  `HOME_TILES`), `index.html` (`#watch-view` + cache-stamp `?v`/`_v` → 96), `sw.js` VERSION → v70,
  `style.css` (`#watch-view` block).
- **Audit** (`docs/evidence/watch/`): screenshots of every state desktop+narrow, console log (0 real
  errors), findings.md. Fixed the cert flat-sparkline → expiry bar.

## Verification
- `python -m unittest tests.test_watch` (25 green); full suite stays green.
- `ruff check` + `ruff format --check` clean on new files; `node --check` on touched JS.
- Playwright audit `docs/evidence/watch/audit.py <port>` → PASS, 0 console errors.

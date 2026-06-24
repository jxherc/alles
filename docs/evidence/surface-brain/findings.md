# surface-brain - evidence

Goal: make the already-built intelligence backend (insights 1e, distilled user-model 1c,
proactive learning 1a) visible in the UI and actually inform aide.

## What was exercised

### Backend (TDD - tests/test_brain_surface.py, 13 tests, all green)
- `insights.inject_active_insights(db)` - formats active insights (pinned first), bounded by
  `limit`, '' when none.
- `user_model.inject_distilled(db)` - excludes vetoed + below-threshold facts, orders by
  confidence, '' when none.
- `routes/chat.py _build_messages` - injects the insights block when `insights_auto_inject` is
  on, the distilled block when `distilled_auto_inject` is on; omits each when off; never injects a
  vetoed fact.
- `POST /api/memory/distill/run` - runs the distill pass, returns `{ran, count}`.
- settings: `insights_auto_inject` / `distilled_auto_inject` default True; SettingsPatch accepts them.

### Live HTTP smoke (fresh instance on :8078, real backend)
- `POST /api/memory/distill/run` -> `{"ran":true,"count":0}` (no model configured, clean).
- `GET /api/insights`, `/api/memory/distilled`, `/api/proactive/stats` all 200.
- `GET /api/settings` includes both new inject keys = true.
- Injection on the persistent DB: seeded an Insight + a distilled fact + a vetoed fact, built a
  chat turn -> system prompt contains the insight + the distilled fact, excludes the vetoed one;
  with both toggles off the prompt is clean. (confirms the 1c migration columns exist live too.)

### Frontend (Playwright - tests/pw_brain_intelligence.py, all PASS)
- brain view renders all three new sections: insights (title + body + evidence tags + pin/dismiss),
  "what aide learned about you" (fact + confidence bar + provenance + pin/veto), proactive learning
  (per-category act-rate + learned weight).
- action buttons POST the right paths: `/api/insights/{id}/pin`, `/api/memory/{id}/veto`,
  `/api/insights/run`.
- disabled state shows a "turn it on" shortcut into the intelligence settings pane.
- new settings "intelligence" pane renders its toggles + the generate/distill-now buttons.
- screenshots: brain_dashboard.png, intelligence_pane.png (judged: on house style, both themes via
  tokens, aligned, confidence bar reads right).

## Regression
- `python -m pytest tests/ -q` -> 3299 passed, 0 failed.
- `node --test tests/js/*.mjs` -> 87 passed.
- `node --check` on brain.js + settings.js clean; `ruff check`/`format` clean on touched py.
- cache stamp bumped sw.js v122 / STAMP 148, index.html style.css?v=148 + _v=148.

## Notes
- brain lives on the `aide` subdomain; the Playwright test boots there with an authed /api/auth/me
  mock so the full app inits (the apex hub does not bind the brain controls).
- new route restart: a running instance needs a restart to pick up `/api/memory/distill/run`.

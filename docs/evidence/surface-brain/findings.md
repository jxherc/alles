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

## Stress test (round 2)

Hammered the feature on three fronts; found + fixed 4 robustness issues (all pre-existing in the
parsing layer but now on a user-facing path).

### backend (in-process, tests/../scratchpad/stress_backend.py)
- parser fuzzing: 24 malformed insight inputs + 31 fact inputs (empty, non-json, non-list, numeric
  fields, 20k-char title, 5000-item array, XSS strings, em/en-dashes, emoji, null bytes).
  FOUND: `insights._parse` + `user_model._parse_facts` crashed on a NON-STRING title/text
  (`'int' object has no attribute 'strip'`) -> a misbehaving model would 500 the generate button.
  FIXED: coerce with `str(...)` in the guards (+ `apply_insights`/`apply_distilled` fields).
- FOUND: `apply_distilled` did not cap text to 300 like `apply_insights` caps its fields.
  FIXED: cap `str(...)[:300]`.
- injection bounds under 2000 insights + 2000 facts: inject stays <= limit lines, pinned first,
  total prompt block sane (<25k / <6k), vetoed + low-confidence never appear, `_build_messages`
  bounded (<30k) with both blocks present.

### http concurrency (stress_http.py, 810 reqs @ 24 workers)
- 0 5xx, 0 transport errors. veto/pin/dismiss/run/list hammered concurrently. (clean 404s were the
  decay job deleting faded facts mid-storm - expected.)

### frontend XSS + edge values + volume (tests/pw_brain_stress.py)
- XSS payloads in title/body/evidence/text/provenance render as INERT escaped text (no alert, no
  injected img/svg/script nodes, window.__xss never set).
- FOUND: a string/negative/null/>1 confidence produced `NaN%` / an overflowing bar.
  FIXED brain.js: `pct = clamp(0,100, round(Number(conf)||0 *100))`.
- FOUND: a 6000-char unbreakable token ran to the viewport edge.
  FIXED css: `overflow-wrap: anywhere` on the text containers (wraps cleanly now).
- volume: 502 insights + 505 facts render, no horizontal overflow.
- evidence: brain_stress.png.

After hardening: full suite 3304 green; cache bumped v123 / 149.

## Notes
- brain lives on the `aide` subdomain; the Playwright test boots there with an authed /api/auth/me
  mock so the full app inits (the apex hub does not bind the brain controls).
- new route restart: a running instance needs a restart to pick up `/api/memory/distill/run`.

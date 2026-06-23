# stage 1a - proactive feedback loop

Close the one-way proactive feed into a loop that learns. Audit: docs/evidence/1a-proactive-feedback.

## design
- `ProactiveOutcome` model (core/database.py): id, item_id, dedupe_key, category,
  outcome (acted|dismissed|ignored), latency_sec (float), created_at.
- `services/proactive.py`:
  - `record_outcome(db, item, outcome)` - write a ProactiveOutcome, latency = now-item.created_at.
  - `_category_weight(db, cat) -> float` - bounded [0.5, 1.5], cold-start 1.0:
    `signal = acts - dismisses - 0.3*ignores; total = acts+dismisses+ignores;
     weight = clamp(1 + 0.5*signal/(total+3), 0.5, 1.5)`.
  - `_upsert`: fold weight into score for both new + live cards:
    `final = max(0, min(100, round(base * _category_weight(db, cat))))`.
  - `_prune_resolved`: before deleting a (non-dismissed) card, `record_outcome(db, item, "ignored")`.
  - `feedback_stats(db) -> dict` - per category {acted, dismissed, ignored, act_rate, weight}.
- `routes/proactive.py`:
  - `POST /{id}/act` - status="acted", dismissed=True, record_outcome(acted). returns {ok}.
  - extend `POST /{id}/dismiss` - also record_outcome(dismissed).
  - `GET /stats` - feedback_stats.
- frontend (static/js/app.js `_renderToday` proactive cards): the card body click POSTs /act
  before navigating; the existing ✕ already POSTs dismiss. cache bump.

## tasks
### Task 1a-1 - outcome model + record + weight + scoring  (tests: tests/test_proactive_feedback.py)
RED tests (>=8): record_outcome writes a row with latency; act endpoint sets status=acted +
dismissed + records acted; dismiss records dismissed; prune records ignored for a resolved card;
cold-start weight == 1.0; repeated dismisses of a category drive weight < 1.0 (toward 0.5);
repeated acts drive weight > 1.0 (toward 1.5); weight bounded [0.5,1.5]; _upsert applies the
weight (a dismiss-heavy category's new card scores below its base; cold-start unchanged);
feedback_stats returns per-category counts + rates + weight; act on a missing id -> {ok:False}.

### Task 1a-2 - frontend act wiring + cache bump  (tests: integration / playwright-lite)
card body click -> POST /api/proactive/{id}/act then navigate. bump sw.js + index.html stamps.
RED/regression: a unit check that the rendered card wires an /act call (jsdom-free: assert the
handler exists via a small DOM-string check or a playwright click asserting the POST).

## verification
- `python -m unittest tests.test_proactive_feedback` green.
- existing proactive tests (test_proactive*, test_api_proactive) still green.
- full suite green; cache stamp bumped.

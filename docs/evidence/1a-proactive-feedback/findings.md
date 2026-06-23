# stage 1a - proactive feedback loop - audit findings (2026-06-23)

## the gap (confirmed in code)
the proactive feed is one-way:
- `ProactiveItem.status` defaults "new" and supports "seen|dismissed|acted", but **"acted" is
  never written anywhere** (grep). routes/proactive.py dismiss only sets status="dismissed".
- `services/proactive.py:_upsert` sets `score` straight from the LLM (`c["score"]`, lines 237 +
  245-247). nothing reads past dismissals/actions back into scoring - the score is immutable.
- `_prune_resolved` (line 190) DELETES live cards whose signals are gone, leaving NO record of
  whether the user engaged. so there is no outcome history at all.
- no per-category learning, no cadence signal, no feedback-stats surface.

result: the feed cannot tell which card types the owner acts on vs ignores; a few useless card
types quietly turn the whole feed into noise.

## fix
1. `ProactiveOutcome` model: (item_id, dedupe_key, category, outcome acted|dismissed|ignored,
   latency_sec, created_at) - one row per card fate.
2. endpoints: `POST /api/proactive/{id}/act` (status=acted + dismissed=True so it leaves the
   feed + record outcome with latency); extend dismiss to record an outcome; `GET /api/proactive/
   stats` (per-category act/dismiss/ignore + rate + current weight).
3. `_prune_resolved`: record outcome "ignored" for each non-dismissed card it deletes (it was
   shown but never acted/dismissed before the situation resolved).
4. `_category_weight(db, cat)`: bounded [0.5, 1.5], cold-start 1.0, favors acted, penalizes
   dismissed (and weakly ignored). folded into `_upsert` score (new + live):
   `score = clamp(round(base * weight), 0, 100)`.
5. frontend: a proactive card's body click POSTs /act before navigating (`_renderToday`).
6. latency_sec is captured for cadence learning; the push-window gating itself is a small
   future add (data captured now, gating deferred to keep this stage bounded).

rides the 0c `events.subscribe()` foundation conceptually (outcomes are the first real consumer
of behavioral signal); the weight + stats are pure DB reads, no async.

verified: created a ProactiveItem - status "new", no ProactiveOutcome model, "acted" unused.

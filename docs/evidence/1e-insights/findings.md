# stage 1e - cross-domain causal insights - audit findings (2026-06-23)

## the gap
the app now has a lot of cross-domain data (signals history from 1b, money/habits/journal/tasks,
the 1a proactive outcomes) but nothing ever looks ACROSS it for higher-level, causal patterns
("your most productive days cluster after social events", "spending spikes 2-3 weeks after a sub
price hike"). proactive cards are about the immediate now; this is about the meta-pattern over
weeks. no Insight model exists.

## fix (mirrors the 1c distill pattern - a gated, model_fn-seam pipeline)
- `Insight` model: id, kind, title, body, evidence (json list of refs), pinned, dismissed,
  created_at.
- `services/insights.py`:
  - `gather_corpus(db)` - a compact structured summary across signal-snapshot history +
    money/habits/journal/task stats + proactive category prefs. deterministic.
  - `apply_insights(db, items)` - upsert; dedupe by the evidence set; never recreate a dismissed
    insight (its evidence-key stays suppressed). returns count.
  - `generate_async(db, model_fn=None)` - gather -> model -> parse -> apply. model_fn is the test
    seam; default reuses the configured model. gated by `insights_enabled`.
- routes/insights.py: GET /api/insights (non-dismissed, pinned first), POST /{id}/pin,
  POST /{id}/dismiss, POST /run (gated, force for the run-now button).
- setting `insights_enabled` (default False - spends tokens) + a gated daily job.

default OFF + evidence-cited so the user can see WHY. verified: no Insight model;
agent_runtime.run_agent available for the real path.

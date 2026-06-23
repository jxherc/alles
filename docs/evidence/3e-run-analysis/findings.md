# stage 3e - agent run analysis + replay - audit findings (2026-06-23)

## current state
- `services/agent_state.py` persists every agent run as a JSON file (data/agent_runs/<id>.json) with
  model, status, turn count, tool_steps, events, timestamps. rich raw data.
- but NOTHING reads it back analytically: no per-run summary, no clustering of similar runs, no
  extraction of past successful runs as few-shot precedents, no replay. the run logs are write-only.
- the run does NOT record the user's intent (the prompt) - start_run takes session/model/turns only, so
  a run can't be matched to "what was asked".

## the gap
- a summary per run (intent, tools used, status, turns, duration).
- cluster runs by intent so repeated kinds of work are visible.
- pull SUCCESSFUL past runs matching a new request as few-shot precedents for the system prompt.
- a replay plan: rebuild a past run's input with a different model/effort.

## fix
- stamp `intent` onto the run in run_agent (the last user message), so runs become self-describing.
- new `services/run_analysis.py` (pure over run dicts + a disk loader):
  - `summarize(run)` -> {id, intent, tools, status, turns, duration_sec}.
  - `cluster_by_intent(runs)` -> {intent_key: [summaries]} (normalized intent, tool-signature fallback).
  - `precedents(runs, query, k)` -> top SUCCESSFUL runs whose intent overlaps the query (few-shot source).
  - `precedents_text(...)` -> a compact block to inject into the system prompt.
  - `replay_plan(run, *, model, effort)` -> {messages, model, effort} to re-submit (no LLM call here).
  - `load_runs(limit)` reads the JSON files newest-first.
- routes: GET /api/agent/runs/analysis + GET /api/agent/runs/{id}/replay-plan.

tested (pure, in-memory run dicts + one disk round-trip): summarize, cluster grouping, precedents
success-only + ranking + text, replay_plan override, load_runs, empty-graceful.

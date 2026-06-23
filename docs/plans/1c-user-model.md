# stage 1c - memory auto-distillation

Audit: docs/evidence/1c-user-model. Build a living user model distilled from behavior into a
"distilled" memory lane, injected into aide. LLM stubbable; rides 1a outcomes.

## design
- Memory + `confidence` (Float, default 1.0), `vetoed` (Boolean, default False),
  `provenance` (String, default "") - added via migration `core/migrations/m0002_memory_distill.py`
  (first numbered migration beyond baseline; validates the 0a framework on an existing table).
- `memory_store.search_memories`: filter `Memory.vetoed == False`.
- `services/user_model.py`:
  - `gather_evidence(db, *, sessions=20)` -> {topics: [recent session titles/first-msgs],
    cadence: {median latency from ProactiveOutcome acted}, category_prefs: {cat: act_rate}}.
  - `apply_distilled(db, facts, provenance="") -> int` - facts = [{text, category, confidence}];
    upsert source="distilled" (dedupe by normalized text; skip if a vetoed memory has that text).
  - `decay(db, *, factor=0.85, floor=0.25) -> int` - distilled non-pinned: confidence *= factor;
    delete those < floor. returns dropped count.
  - `veto(db, mid) -> bool` - set vetoed=True (excluded from inject + never re-distilled).
  - `distill_async(db, model_fn)` - gather_evidence -> model_fn(evidence) -> parse -> apply.
    (model_fn thin; the job supplies the real model; tests pass a fake.)
- routes/memory.py: `GET /api/memory/distilled` (source=distilled list), `POST /api/memory/{id}/veto`.
- settings: `user_model_distill` bool=False (token spend). job `user_model` (daily,
  run_at_start=False) runs distill_async+decay only when enabled.

## tasks
### Task 1c-1 - migration + columns + distilled lane core  (tests: tests/test_user_model.py)
RED tests (>=8): m0002 has VERSION==2; m0002 adds the 3 columns to memories (run on a stripped
table); apply_distilled creates a source=distilled Memory with confidence + provenance;
apply_distilled dedupes by text (no duplicate); apply_distilled skips a vetoed text; decay lowers
confidence; decay drops a below-floor non-pinned fact but keeps a pinned one; veto sets vetoed +
excludes from search_memories; gather_evidence returns topics + category_prefs from seeded
sessions + ProactiveOutcome; distill_async with a fake model_fn writes the returned facts.

### Task 1c-2 - routes + setting + injection  (tests: tests/test_user_model.py cont.)
RED tests: GET /api/memory/distilled lists only distilled; POST /api/memory/{id}/veto hides it;
setting default False; inject_memories includes a distilled fact and excludes a vetoed one.

## verification
- `python -m unittest tests.test_user_model` green; memory route tests still green; full suite green.

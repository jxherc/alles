# stage 1c - memory auto-distillation - audit findings (2026-06-23)

## current memory system
- `Memory` model: text, category (identity|preference|fact|task|general), source
  (manual|extracted|imported), session_id, pinned, timestamp. NO confidence, NO veto, NO
  provenance, no "distilled" source.
- `services/memory_store.py`: add_memory / get_all / delete / update / search_memories /
  `inject_memories` (the system-prompt feed). search queries ALL memories (no veto filter).
- injection: `routes/chat.py:159` - `if memory_auto_inject: inject_memories(user_text)`.

## the gap
memory is **entirely hand-authored** - the user types facts in. nothing watches behavior:
repeated conversation themes, which proactive cards get acted on vs ignored (the 1a outcomes!),
preferred cadence, what kinds of help the user asks for. there is no living user model, so aide
+ proactive stay generic no matter how much the user interacts.

## fix
- Memory gains `confidence` (float), `vetoed` (bool), `provenance` (str) - added to the EXISTING
  table via a real numbered migration `m0002` (first use of the 0a framework beyond baseline).
- `services/user_model.py`:
  - `gather_evidence(db)` - recent session topics + ProactiveOutcome cadence/category-prefs (1a).
  - `apply_distilled(db, facts, provenance)` - upsert facts as source="distilled" w/ confidence;
    dedupe by text; never re-create a vetoed fact.
  - `distill_async(db, model_fn)` - gather -> model -> apply (the job; model call thin/stubbable).
  - `decay(db)` - age distilled non-pinned facts' confidence; drop the faded ones.
  - `veto(db, mid)` - hide a distilled fact + keep it from coming back.
- `memory_store.search_memories` filters `vetoed == False` so distilled facts inject but vetoed
  ones never do.
- routes: list distilled + veto. setting `user_model_distill` (default False - spends tokens) +
  a daily job that distills+decays when enabled.

verified: no confidence/veto/distilled today; inject_memories pulls every memory.

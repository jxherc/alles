# stage 1b - signal history + cross-domain synthesis

Audit: docs/evidence/1b-synthesis. gather() stays pure; snapshots written on the periodic
proactive path; synthesize() reads history to emit derived signals.

## design
- `SignalSnapshot` model (core/database.py): id, ts (index), category (index), key, urgency,
  data (Text json). a rolling history.
- `services/signals.py`:
  - `record_snapshot(db, sigs, *, keep_days=30)` - one row per signal with utcnow ts; trims rows
    older than keep_days. returns count written.
  - `synthesize(db, now=None) -> list[_sig]` - read snapshots within a window (e.g. 14 days):
    - `trend:<cat>`: a category whose per-snapshot count rose over the window (compare the
      earliest vs latest buckets) -> _sig(category="trend", key=f"trend:{cat}", urgency from the
      slope, title, detail, link, data={delta, from, to}, explain="...").
    - `corr:<a>:<b>`: two categories that co-occur in the same snapshots above a threshold ->
      _sig(category="corr", key=f"corr:{a}:{b}", ...). deterministic, sorted keys so a:b stable.
    - each derived sig carries `explain`. pure: no writes.
  - extend `_sig` callers' shape with an optional `explain` (default "") so derived sigs carry it
    without breaking the existing 7-field dict (add explain only on derived).
- `services/proactive.py:run`: after gather(full), if `pidx_proactive_synthesis` (default True):
  `record_snapshot(db, full)` then `full = full + synthesize(db)` before reasoning/upsert.
- settings: `pidx_proactive_synthesis` bool=True (core/settings.py defaults + routes/settings.py
  SettingsPatch).

## tasks
### Task 1b-1 - SignalSnapshot + record_snapshot + synthesize  (tests: tests/test_synthesis.py)
RED tests (>=8): record_snapshot writes one row per signal with ts + category; record_snapshot
trims rows older than keep_days; synthesize on empty history -> []; a rising overdue-task count
across seeded snapshots -> a `trend:task` derived signal; the trend sig carries explain + a
positive delta in data; co-occurrence of two categories over the window -> a `corr:` signal with
a stable sorted key (corr:a:b not corr:b:a); synthesize is deterministic (two calls on the same
history equal); a flat/declining count emits no trend; derived signal keys are stable across
calls (dedupe-safe).

### Task 1b-2 - proactive merge + opt-out setting  (tests: tests/test_synthesis.py cont.)
RED tests (>=8 combined): the setting defaults True; with synthesis on, a proactive run records a
snapshot; with synthesis off, no snapshot + no derived signals merged; synthesize output is
appended to the gather set passed to reasoning (assert via a seam); today.py + briefing remain
byte-stable (they don't call synthesize). reuse the existing proactive test seams.

## verification
- `python -m unittest tests.test_synthesis` green.
- today golden + briefing tests unchanged (gather still pure).
- full suite green.

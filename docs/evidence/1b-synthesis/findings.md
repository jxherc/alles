# stage 1b - signal history + cross-domain synthesis - audit findings (2026-06-23)

## current state
`services/signals.py:gather(db, today, *, categories)` computes 12 categories of point-facts
(_COLLECTORS) and sorts by urgency. it is explicitly **pure read** (docstring) and is called on
every today-widget load (routes/today.py), every briefing (services/briefing.py), and every
proactive run (services/proactive.py). `by_category` groups them.

## the gap
- **no history**: signals are recomputed fresh each call and thrown away. there is no record of
  "overdue tasks rose from 2 to 7 over the week" - the time dimension is invisible.
- **no synthesis**: every signal is a raw, isolated fact. nothing correlates across categories
  (habits slipping + budget creeping), detects trends, or emits higher-level insight. consumers
  (today/briefing/proactive) only ever see the raw list.

## design constraint (important)
`gather()` must STAY pure - it runs on every page load; writing snapshots there would hammer the
DB. so snapshots are written on the **periodic proactive path** (already scheduled, low
frequency), not in gather(). synthesis reads that history and is a pure read.

## fix
1. `SignalSnapshot` model (ts, category, key, urgency, data) - a rolling history, trimmed.
2. `signals.record_snapshot(db, sigs)` - persist the current signal set; called from the
   proactive run (periodic), NOT gather().
3. `signals.synthesize(db, now=None) -> list[_sig]` - read recent history, emit derived signals
   with their own stable keys + an `explain` field:
   - `trend:<category>` when a category's count/urgency rises across the window.
   - `corr:<a>:<b>` when two categories co-occur over the window.
   pure + deterministic on a fixed history.
4. proactive run merges synthesize() output into its signal set (behind a default-on setting
   `pidx_proactive_synthesis`); today/briefing unchanged (stay byte-stable).

verified: gather() is pure; no SignalSnapshot model; consumers read only the raw list.

## status
audit + plan complete (docs/plans/1b-synthesis.md). implementation pending - clean checkpoint
(suite green at 2835, no RED tests left). next: TDD record_snapshot + synthesize + proactive merge.

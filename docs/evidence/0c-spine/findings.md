# stage 0c - event/mutation spine - audit findings (2026-06-23)

## what exists
- `services/jobs.py` event bus: `on(event, handler)` + `async emit(event, **data)`. process-local,
  best-effort, EPHEMERAL (no record kept). exercised live: emit fires both sync + async handlers.
  used in exactly ONE place repo-wide: `routes/watch.py:171` (`await jobs.emit(...)`).
- automations react by POLLING: `run_automations()` runs every 30s (app.py job) reading the
  CURRENT db state; the doc/agent hooks (`on_doc_saved`/`on_agent_tool`) fire from 2 call sites.
- `@event.listens_for(engine,"connect")` (WAL pragma) is the ONLY SQLAlchemy listener. There are
  NO mapper `after_insert/after_update/after_delete` or session `after_commit` listeners anywhere.

## the gap
nothing records "what changed, when". a task completing, a transaction posting, a subscription
renewing - none leave a durable trace. so:
- no audit / history / undo substrate
- automations can only poll (stale snapshots, 30s latency, re-scans the whole table)
- the learning brain (proactive outcomes, memory distillation, cross-domain synthesis) has no
  event stream to consume - it would have to re-derive everything from current state each time

## fix (the keystone)
a durable `MutationEvent` log written by SQLAlchemy mapper listeners on a curated TRACKED set of
models (Task, Transaction, Subscription, CalendarEvent, Note, JournalEntry, Habit, ProactiveItem),
written via the same `connection` so it commits/rolls-back WITH the host transaction. plus a
synchronous `subscribe(fn)` API fired after_commit with the txn's committed mutations (best-effort,
a bad subscriber can never break a commit). additive: the async bus + the 30s automations poll
stay as-is. listeners are bulletproof (a listener failure logs + is swallowed, never breaks the
host write).

verified pre-state: no MutationEvent model, no listeners. both axes for the existing bus pass
(emit works), it's just ephemeral + barely used.

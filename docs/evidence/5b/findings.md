# 5b audit — mail: send control

No scheduled-send / undo / snooze infrastructure exists. `core/database.py` has no ScheduledMail
or snooze field (the one "scheduled" hit is the RecurringTxn comment). Live `:8841`: /schedule,
/scheduled, /snooze all 404. The jobs system (`services/jobs.py`) exposes `register(name, fn,
interval)` — I'll register a 30s `process_due` job for the outbox.

All net-new. Plan: docs/plans/5b.md (5b-1 backend outbox + snooze cache field, 5b-2 frontend).

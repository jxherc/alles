# stage 2g - mail rules engine completion - audit findings (2026-06-23)

## current state
- `MailRule.action` declares 4 actions: markread | mute | label | autoreply.
- `mail_rules.run_on_cache` only EXECUTES markread + mute. label + autoreply match (apply_rules
  returns them) but run_on_cache silently ignores them - dead actions. exercised: a label rule "runs"
  and reports applied=0, the label never lands on CachedMessage.labels (which exists, line 1057).
- `vacation_reply_for` is a pure one-reply-per-sender-per-day function but is NEVER called anywhere -
  it has no hook into the outbox, so a vacation responder never actually sends. grep confirms zero
  callers outside its own test.
- the outbox (`ScheduledMail` + `services/mail_outbox.process_due`) works + is wired to a 30s job; it's
  the natural sink for autoreply + vacation sends but nothing enqueues into it from rules.

## the gap
1. run_on_cache must execute `label` (append to CachedMessage.labels, deduped) and `autoreply`
   (enqueue a ScheduledMail reply, once per message).
2. autoreply needs an idempotency guard so re-running rules doesn't re-enqueue - no such flag exists.
3. vacation_reply_for needs a driver that walks inbound messages, enqueues replies via the outbox, and
   persists the per-sender-per-day state.

## fix
- migration m0004: add `autoreplied` BOOLEAN to cached_messages (the autoreply guard).
- `mail_rules._enqueue(db, account_id, to, subject, body)` -> creates a ScheduledMail(send_at=now);
  process_due (already running) sends it.
- run_on_cache: `label` -> dedup-append action_arg into row.labels; `autoreply` -> if not
  row.autoreplied, enqueue a reply + set the guard. both counted.
- `mail_rules.run_vacation(db, account_id, vac, state, today)` -> for each cached sender, call
  vacation_reply_for, enqueue produced replies, return (count, new_state). route POST
  /mail/vacation/run/{aid} loads state from settings (mail_vacation_state), runs, saves it.

matching/vacation logic stays pure; enqueue + label are locally testable against the cache + outbox.

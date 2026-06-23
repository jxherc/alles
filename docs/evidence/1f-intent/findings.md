# stage 1f - intent prediction + contextual suggestions - audit findings (2026-06-23)

## current state
`services/agent_intents.py:message_needs_tools(text)` is REACTIVE - it pattern-matches a message
to decide whether to auto-promote a chat turn to an agent turn. aide never ANTICIPATES: it waits
for an explicit request, never offers "want me to find hotels for that trip?" when the calendar
shows travel, or "review your overdue tasks" when several are due.

## the gap
no forward-looking suggestion: nothing fuses the current signals (1-now), the session topic/mode
(1d), and the latest composer text into 1-2 likely next-step suggestions surfaced in the UI.

## fix (deterministic, rides 1b/1d)
- `services/intent.py`:
  - `predict_suggestions(db, *, message="", session=None, limit=2) -> list[{label, link, kind}]`
    - candidates from current signals (overdue tasks -> review tasks; sub renewing -> renewals;
      event soon -> schedule) ranked by urgency, plus from the latest user message / composer text
      (budget/spend -> spending; trip/flight/hotel -> plan trip). dedupe, top `limit`.
- `routes/chat.py`: `GET /api/aide/suggestions?session_id=&q=` -> predict_suggestions
  (gated by `intent_suggestions`, default True).
- frontend: a small chips row above/below the composer; a chip click fills the input with the
  suggestion's prompt. cache bump.

deterministic heuristics keep it testable + free. verified: message_needs_tools is reactive-only;
no prediction surface exists.

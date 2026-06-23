# stage 1d - conversational / session-scoped memory - audit findings (2026-06-23)

## current state
`routes/chat.py` builds the system prompt then injects long-term memories
(`inject_memories(user_text)`, lines 159-162) and an artifacts block. the message list is
`[system] + last N session.messages`. so the model DOES see recent turns (history), but it gets
NO distilled session-scope: it can't state "we're in debugging mode on the auth refactor" - it
re-derives intent from raw history every turn, repeats itself, and loses the working thread on
long sessions.

## the gap
no per-session context summary: inferred MODE (research|planning|debugging|writing|chat),
current TOPIC, and the active PROJECT (session.project_id is set but never surfaced to the
model as context).

## fix (deterministic, no extra LLM call)
- `services/session_context.py`:
  - `infer_mode(user_texts) -> str` - keyword-scored heuristic over recent user turns.
  - `summarize(db, session, *, recent=12) -> str` - mode + a short topic (from the latest
    substantive user line) + the project name (looked up from session.project_id). compact,
    length-budgeted. "" for an empty session.
- `routes/chat.py`: after the memory inject, append the session-context block to the prompt
  (gated by a default-on setting `session_context_inject`).

deterministic heuristics keep it testable + free (no model call). verified: session.messages +
session.project_id are available where the prompt is built; nothing summarizes them today.

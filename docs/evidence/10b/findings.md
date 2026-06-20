# 10b — background agents (durable detached runs): implementation + regression

## Audit
`POST /api/agent/background` already detaches via `asyncio.create_task` and survives tab close;
`agent_state.record_event` persists `events[]` to JSON on every event. Gaps: assistant prose wasn't
persisted incrementally; no tail endpoint for reconnect; frontend never reattached to a live run.

## Built (strict TDD, ruff + node-check clean — no new lint errors)
- **10b-1 durable state + reconnect tail** — run JSON now carries `text` (accumulated prose), persisted
  by `run_agent` each turn + at done so a reconnect sees the answer-so-far. New
  `GET /api/agent/runs/{id}/events?since=N` → `{events[N:], next, status, text, turn, done}` — a durable,
  pollable tail. 10 unit tests.
- **10b-2 frontend reattach** — `static/js/bgrun.js` `reattach(sessionId)`: on session (re)open,
  `selectSession` checks `/api/agent/runs/active`; if a run is live it shows a "running in background"
  block and tails `/events` (text + status) until done, then refreshes the conversation. 7 Playwright
  assertions incl. survives-reload and clears-on-done; 0 console errors. Stamps v72 / SW v46.

## Regression
16 subdomains 0 console errors (`docs/evidence/10b/regression/`). Full suite: 1621 tests OK.

## Note
The existing `/api/agent/background` endpoint is the run primitive; 10b made runs *observable* across a
reload. The pw test seeds a durable 'running' run on disk and confirms the UI picks it up — this is the
"start a run, close the tab, reopen → it continued and shows progress" acceptance.

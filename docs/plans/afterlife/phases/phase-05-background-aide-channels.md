# Afterlife Phase 5 — background Aide and channels

- **Status:** delivered
- **Started:** July 14, 2026
- **Rule:** Aide is the only in-app assistant. Jarvis is only the Discord bot.
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

## Goal

Finish the one-mode Aide experience around the durable background system that already exists. Keep old
`jarvis_*` database and API names internal for compatibility. Normal product copy says Aide, work,
schedule, run, or connection.

## Already working

- [x] Aide has one tool-capable mode with no visible Chat, Agent, Jarvis, or Answer-only selector.
- [x] New tasks can use no folder, an existing Project, or a newly selected server folder.
- [x] Project, model, permission, effort, attachment, and task context survive task creation.
- [x] Durable workflows, triggers, runs, events, choices, approvals, leases, retries, cancellation,
  recovery, and delivery records exist.
- [x] Exact schedules, intervals, heartbeats, reviewed events, and webhook triggers exist in the backend.
- [x] Home reads local durable records into **Needs you**, **In progress**, and **Briefs**.
- [x] MCP servers already support encrypted private values, connect/disconnect, tool calls, and scoped
  grants.

Fresh delivery evidence: 109 focused backend tests, 197 JavaScript tests, five browser gates, and a
computer-control review passed on July 14, 2026 using isolated data.

## Post-delivery stabilization

- [x] Keep a Project branch menu attached to its branch control.
- [x] Allow Git to carry non-conflicting uncommitted changes across local branch switches; stop only
  when Git reports a real overwrite conflict, and preserve the work.
- [x] Keep Home's Aide brief short and remove raw Markdown before display.
- [x] Make the square operating-system logo shimmer repeat by one exact gradient tile so it loops
  without an end-frame jump; reduced motion remains static.

## 5A — finish background Aide

- [x] Make **scheduled** open a dedicated, compact Aide screen instead of unrelated Rules settings.
- [x] List schedules and recent work with clear next-run, state, Project, and recovery actions.
- [x] Create and edit the common schedule types without native menus: exact time, interval, and
  heartbeat. Keep advanced event/webhook controls available without crowding the default view.
- [x] Keep background progress, questions, approval, failure, retry, cancel, and completion inside the
  originating Aide task when a task has one.
- [x] Replace visible legacy Jarvis runtime wording with Aide wording. Keep compatibility URLs and
  storage names internal.
- [x] Remove the obsolete dedicated Proactive page while keeping useful background checks available
  through schedules and Settings.
- [x] Keep MCP management under Connections and verify existing scope and secret protections.

## 5B — Jarvis Discord connection

- [x] Add one revocable Jarvis Discord connection with an encrypted bot token.
- [x] Pair exactly one owner Discord account through a short-lived one-time code.
- [x] Allow owner DMs and individually approved private channels only; ignore bots, webhooks, unknown
  users, and unknown channels.
- [x] Let Discord start allowed Aide work, read status, answer non-mutating choices, and receive safe
  completion/failure/input-needed notices.
- [x] For normal replies, show Discord typing and stream one answer message in place without a
  separate “started in Aide” message.
- [x] Keep one persistent Aide conversation per paired Discord DM or approved channel so follow-up
  messages retain context instead of creating a new task every time.
- [x] Keep Discord-origin mutations read-only until approved inside Alles.
- [x] Deduplicate inbound events and survive reconnects, restarts, revoked pairing, and quiet hours.

## Gate

- [x] Backend, JavaScript, browser, keyboard, reduced-motion, desktop, and mobile checks pass with
  isolated data.
- [x] Computer-control review finds no clipping, overlap, broken spacing, dead control, native menu, or
  console error in Aide, scheduled work, Projects, Connections, and Home.
- [x] `specifications.md`, the phase index, and current-stage status describe only the delivered result.

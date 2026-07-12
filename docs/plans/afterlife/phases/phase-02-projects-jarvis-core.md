# Afterlife Phase 2 — folder Projects and durable Jarvis core

- **Status:** planned
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** Phase 1 delivered
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

## Goal

Make Projects real folder-based work environments and build the safe background engine Jarvis will use.

At the end of this phase:

- a Project starts work inside its selected folder;
- General works without a folder;
- moved or missing folders can be relinked without losing threads;
- Jarvis runs, schedules, questions, approvals, retries, and deliveries survive restarts;
- uncertain outside actions are never repeated automatically.

This phase builds the foundation. The final Aide/Jarvis screens, Discord bot, News, and Today delivery
come in later phases.

## 2A — folder Projects

- [x] Inventory the current Project, session, instruction, scratchpad, and working-directory behavior.
  - Record what can be reused before changing the schema.
  - Preserve existing IDs, dates, names, chats, instructions, and scratchpads.
- [x] Add the **General** no-folder environment.
  - General supports normal Aide threads without pretending a folder exists.
  - General is not allowed to become an unrestricted filesystem root.
- [x] Make one selected server folder the Project environment.
  - Commands start in the Project folder.
  - Relative paths resolve there.
  - Search and context look there first.
  - New files and generated output default there.
  - Only files needed for the request are selected; the whole folder is not uploaded to a model.
- [ ] Keep outside-folder work possible but visible.
  - Approved extra roots keep their existing read/write rules.
  - Every run records when work leaves the Project folder.
  - A delegated action outside the folder must pass the permission gate in 2D.
- [x] Add clear folder states.
  - Available.
  - Missing.
  - Relink required.
  - Relinking requires an explicit owner choice; Alles never guesses a replacement folder.
- [x] Keep Projects small.
  - Store only name, canonical folder path, instructions, scratchpad, color, thread links, and
    last-opened state.
  - Tasks, notes, files, saved searches, and other app records remain owned by their existing apps.
  - Do not create cross-app Project membership tables.
- [x] Keep server and browser folders separate.
  - A folder chosen in a remote browser is not treated as a server folder.
  - Client-local access waits for an approved mount or future desktop bridge.
- [x] Migrate current Projects safely.
  - Existing valid working directories become Project folders.
  - Invalid paths become **Folder missing** without deleting the Project or its threads.
  - The migration is safe to run twice.
- [x] Add the small Task-stage bridge Jarvis needs before the full Plan board ships.
  - Preserve the current `done` behavior and existing task data.
  - Add compatible **Doing** and **Waiting** states.
  - Starting work may move a task to Doing; a paused run may move it to Waiting.
  - After success, Jarvis asks before marking the task Done.

Fresh evidence: 92 focused Project, session, General-boundary, Task, recurring-task, and migration tests
pass. All 25 canonical schema histories pass staged restore, repeat migration, and boot. An isolated
live browser pass at 1280×800 and 390×844 verifies keyboard relinking, missing-folder recovery with the
thread preserved, scratchpad saving, reduced motion, no horizontal overflow, and zero console/page
errors. The outside-folder checkbox stays open until the shared delegated-action gate in 2D exists.

### 2A gate

A command and relative output begin inside the selected folder. General works without a fake folder.
Outside-folder work is visible and permission-checked. Moving a folder keeps all Project data and asks
for an explicit relink.

## 2B — durable Jarvis records

- [ ] Add separate durable records for these responsibilities:
  - **Workflow** — reusable task definition and maximum permissions.
  - **Trigger** — manual, schedule, interval, heartbeat, event, or webhook start condition.
  - **JarvisRun** — one execution and its current state.
  - **RunEvent** — append-only progress, source, tool, checkpoint, and output events.
  - **RunPrompt** — a durable question, choice, or approval request.
  - **DeliveryAttempt** — one persistent outbox item and its retry state.
  - **Connector** — encrypted channel configuration and allowlists.
- [ ] Use clear run states.
  - Queued, running, waiting for input, waiting for approval, paused, succeeded, failed, cancelled,
    interrupted, and uncertain.
- [ ] Keep choices and approvals separate.
  - A choice selects a non-mutating path.
  - An approval authorizes one exact mutation, target, data set, privacy effect, cost, expiry, and
    capability.
  - Approvals are single-use, expire, survive restart, and re-check the action before execution.
- [ ] Add safe checkpoints before and after tool actions.
  - Record enough state to explain what happened after a crash.
  - Do not store secrets, full private content, or unsafe tool output in progress events.
- [ ] Reconcile interrupted legacy background work honestly.
  - Proven incomplete work may resume.
  - Proven complete work is not repeated.
  - An outcome that cannot be proved becomes **uncertain** and asks the owner.
- [ ] Add compatibility reads while old automation APIs are still used.

### 2B gate

Runs, events, prompts, approvals, and delivery state survive a server restart. A crash immediately before
or after an outside action never causes a blind duplicate action.

## 2C — scheduler and heartbeat

- [ ] Store schedule times as UTC plus the owner's selected timezone.
- [ ] Give every occurrence a stable `scheduled_for` identity.
  - Enforce one occurrence per workflow, trigger, and scheduled time.
- [ ] Claim queued work with leases.
  - A worker renews its lease while running.
  - A stale lease can be reclaimed after a crash.
- [ ] Default workflow concurrency to one.
  - Add explicit skip, queue, or parallel behavior only where the workflow allows it.
- [ ] Add bounded retry rules.
  - Transient failures retry with backoff and a limit.
  - Permanent failures stop.
  - Uncertain external effects never retry automatically.
- [ ] Handle missed schedules.
  - Repeating schedules coalesce missed occurrences into one current run.
  - A one-time schedule runs once inside its grace window, otherwise it is marked missed.
- [ ] Add heartbeat fingerprints.
  - Run cheap local checks first.
  - No changed signal means no model call and no notification.
  - Store enough fingerprint state to survive restart.
- [ ] Cover quiet hours, skip-when-busy, cost limits, and only-notify-when-useful policy in the data
  model, even if the complete UI comes later.
- [ ] Test daylight-saving changes even when the test server is in a timezone without DST.

### 2C gate

Two workers cannot claim the same occurrence. Restart and stale-lease tests do not lose or duplicate a
run. Heartbeats with unchanged input spend no model call and send no delivery.

## 2D — delegated actions and capability grants

- [ ] Route Aide-, Jarvis-, and tool-origin mutations through one delegated-action gate.
- [ ] Scope grants to exactly one place:
  - General Aide;
  - one Project; or
  - one Workflow.
- [ ] Apply the same grants to existing MCP tools.
  - Tool schemas, prompts, resources, and outputs remain untrusted input.
  - A tool cannot grant itself access or widen its Project/Workflow scope.
- [ ] Begin new external roots read-only.
- [ ] Pause when a requested action exceeds the current grant.
  - Show the exact action, target, data, privacy effect, and cost when known.
- [ ] Keep normal direct owner actions normal.
  - Existing authentication, CSRF, scope, recent-auth, and confirmation rules still apply.
  - Do not create fake Jarvis approvals for ordinary owner editing.
- [ ] Record grant creation, use, denial, expiry, revocation, and approval use without logging private
  content or secrets.

### 2D gate

A workflow cannot act outside its Project or grant without a durable exact approval. Revoking a grant
blocks the next action immediately, including after restart.

## 2E — outbox, events, and automation migration

- [ ] Build one persistent delivery outbox without Discord-specific behavior.
  - Store run/event, channel type, privacy level, attempt count, next attempt, safe error class,
    provider message ID, and final state.
  - Keep workflow success separate from delivery success.
- [ ] Make delivery retries idempotent where a provider supports an idempotency key.
- [ ] Mark an unprovable delivery result **uncertain** instead of sending it again.
- [ ] Add small event hooks from existing apps.
  - Hooks enqueue reviewed events; they do not run model work inside the app request.
  - External content stays untrusted and cannot approve its own action or create trusted memory.
- [ ] Convert current automations into paused Workflows and Triggers.
  - Preserve names, schedules, enabled intent, and action details where safe.
  - Require owner review of model, permissions, delivery, and schedule before enabling.
  - Do not silently activate a migrated automation.
- [ ] Keep connector secrets in the encrypted Phase 1 credential path.

### 2E gate

Outbox items survive restart, do not duplicate a proven delivery, and expose delivery failure separately
from run failure. Every migrated automation starts paused and reviewable.

## Phase 2 verification

- [ ] Add focused unit tests for Project paths, General, missing folders, relinking, run states, leases,
  occurrence uniqueness, retries, heartbeats, approvals, grants, and outbox behavior.
- [ ] Add migration fixtures from every supported older database shape and run each migration twice.
- [ ] Add crash tests immediately before and after each test side effect.
- [ ] Test transient, permanent, and uncertain failures separately.
- [ ] Test two scheduler workers racing for the same occurrence.
- [ ] Test server restart while queued, running, waiting, paused, delivering, and uncertain.
- [ ] Test malicious MCP/tool output attempting to widen permissions or approve itself.
- [ ] Test Project traversal, symlink escape, missing mount, relink, and approved outside-root behavior.
- [ ] Run the full Python and JavaScript suites with throwaway `ALLES_DATA`.
- [ ] Run isolated desktop and 390×844 browser checks with keyboard access, visible focus, reduced motion,
  no overflow, and zero console/page errors.
- [ ] Re-run encrypted backup/restore because this phase changes durable data.
- [ ] Run Ruff checks without rewriting unrelated legacy files.

## Phase 2 exit gate

Phase 2 is delivered only when all of these are true:

1. Project commands and relative outputs start in the selected folder.
2. Outside-folder work is visible and permission-checked.
3. Missing folders require relinking while threads and settings remain intact.
4. Choices, approvals, runs, retries, schedules, and delivery state survive restart.
5. Scheduled occurrences and deliveries do not duplicate under worker races or normal retries.
6. An uncertain outside effect is never retried automatically and clearly asks the owner.
7. Migrated automations remain paused until reviewed.
8. No new secret, private content, unauthenticated exposure, or restore blocker is introduced.

## Not part of Phase 2

- the final Aide/Jarvis interface;
- Discord pairing or Discord message handling;
- News feeds and Today Brief delivery;
- the final product navigation shell;
- a browser-to-server folder bridge;
- broad shell access or unmanaged service control.

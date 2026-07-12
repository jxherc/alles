# Afterlife Phase 2 — folder Projects and durable Jarvis core

- **Status:** in progress
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
- [x] Keep outside-folder work possible but visible.
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
errors. The delegated-action gate adds exact, visible outside-folder actions, keeps extra roots
read-only by default, permits only the approved write targets, records the Aide or Jarvis run, and
blocks symlink escapes.

### 2A gate

A command and relative output begin inside the selected folder. General works without a fake folder.
Outside-folder work is visible and permission-checked. Moving a folder keeps all Project data and asks
for an explicit relink.

## 2B — durable Jarvis records

- [x] Add separate durable records for these responsibilities:
  - **Workflow** — reusable task definition and maximum permissions.
  - **Trigger** — manual, schedule, interval, heartbeat, event, or webhook start condition.
  - **JarvisRun** — one execution and its current state.
  - **RunEvent** — append-only progress, source, tool, checkpoint, and output events.
  - **RunPrompt** — a durable question, choice, or approval request.
  - **DeliveryAttempt** — one persistent outbox item and its retry state.
  - **Connector** — encrypted channel configuration and allowlists.
- [x] Use clear run states.
  - Queued, running, waiting for input, waiting for approval, paused, succeeded, failed, cancelled,
    interrupted, and uncertain.
- [x] Keep choices and approvals separate.
  - A choice selects a non-mutating path.
  - An approval authorizes one exact mutation, target, data set, privacy effect, cost, expiry, and
    capability.
  - Approvals are single-use, expire, survive restart, and re-check the action before execution.
- [x] Add safe checkpoints before and after tool actions.
  - Record enough state to explain what happened after a crash.
  - Do not store secrets, full private content, or unsafe tool output in progress events.
- [x] Reconcile interrupted legacy background work honestly.
  - Proven incomplete work may resume.
  - Proven complete work is not repeated.
  - An outcome that cannot be proved becomes **uncertain** and asks the owner.
- [ ] Add compatibility reads while old automation APIs are still used.

Current evidence: 61 focused record, API, encrypted-credential, key-rotation, backup, and migration
tests pass. All 26 canonical schema histories, both released no-history schemas, and all five Photos-fork
histories pass staged restore, repeat migration, and boot. Workflows and triggers start paused; runs,
events, prompts, deliveries, and connector records use separate tables; connector secrets are masked in
APIs and encrypted in raw SQLite. Durable exact approvals are separate from choices, survive restart,
are single-use under a two-worker race, and create before/after action checkpoints. Startup reconciliation
marks an unconfirmed side effect uncertain and an ordinary stopped run interrupted. Compatibility reads
for migrated automations remain part of 2E.

### 2B gate

Runs, events, prompts, approvals, and delivery state survive a server restart. A crash immediately before
or after an outside action never causes a blind duplicate action.

## 2C — scheduler and heartbeat

- [x] Store schedule times as UTC plus the owner's selected timezone.
- [x] Give every occurrence a stable `scheduled_for` identity.
  - Enforce one occurrence per workflow, trigger, and scheduled time.
- [x] Claim queued work with leases.
  - A worker renews its lease while running.
  - A stale lease can be reclaimed after a crash.
- [x] Default workflow concurrency to one.
  - Add explicit skip, queue, or parallel behavior only where the workflow allows it.
- [x] Add bounded retry rules.
  - Transient failures retry with backoff and a limit.
  - Permanent failures stop.
  - Uncertain external effects never retry automatically.
- [x] Handle missed schedules.
  - Repeating schedules coalesce missed occurrences into one current run.
  - A one-time schedule runs once inside its grace window, otherwise it is marked missed.
- [x] Add heartbeat fingerprints.
  - Run cheap local checks first.
  - No changed signal means no model call and no notification.
  - Store enough fingerprint state to survive restart.
- [x] Cover quiet hours, skip-when-busy, cost limits, and only-notify-when-useful policy in the data
  model, even if the complete UI comes later.
- [x] Test daylight-saving changes even when the test server is in a timezone without DST.

Fresh evidence: 14 focused scheduler tests pass. They cover spring-forward and fall-back DST,
configuration and policy validation, occurrence idempotency, default/skip/queue/parallel behavior,
stale leases, separate transient/permanent/uncertain failures, missed schedules, heartbeat fingerprints,
and a real two-worker SQLite claim race. The complete schema recovery matrix passes all 27 canonical
histories, all five Photos-fork histories, and both released databases without migration history; each
is migrated twice and booted.

### 2C gate

Two workers cannot claim the same occurrence. Restart and stale-lease tests do not lose or duplicate a
run. Heartbeats with unchanged input spend no model call and send no delivery.

## 2D — delegated actions and capability grants

- [x] Route Aide-, Jarvis-, and tool-origin mutations through one delegated-action gate.
- [x] Scope grants to exactly one place:
  - General Aide;
  - one Project; or
  - one Workflow.
- [x] Apply the same grants to existing MCP tools.
  - Tool schemas, prompts, resources, and outputs remain untrusted input.
  - A tool cannot grant itself access or widen its Project/Workflow scope.
- [x] Begin new external roots read-only.
- [x] Pause when a requested action exceeds the current grant.
  - Show the exact action, target, data, privacy effect, and cost when known.
- [x] Keep normal direct owner actions normal.
  - Existing authentication, CSRF, scope, recent-auth, and confirmation rules still apply.
  - Do not create fake Jarvis approvals for ordinary owner editing.
- [x] Record grant creation, use, denial, expiry, revocation, and approval use without logging private
  content or secrets.

Fresh evidence: 21 focused delegation tests pass. They cover General/Project/Workflow scoping,
workflow ceilings, durable Aide and Jarvis approvals, restart recovery, exact-action rechecks, expiry,
immediate revocation, decision and single-use races, read-only external roots, exact approved writes,
symlink escape, content-free events, normal owner edits, MCP default-deny behavior, and malicious MCP
output that tries to widen its own grant. The related 92 Jarvis, scheduler, Aide runtime, background,
worktree, hook, and MCP regression tests also pass with isolated data. The selected delegation and
related regression set is 113 tests total. All 28 canonical schema histories,
all five Photos-fork histories, and both released no-history databases pass repeated migration and boot.

### 2D gate

A workflow cannot act outside its Project or grant without a durable exact approval. Revoking a grant
blocks the next action immediately, including after restart.

## 2E — outbox, events, and automation migration

- [x] Build one persistent delivery outbox without Discord-specific behavior.
  - Store run/event, channel type, privacy level, attempt count, next attempt, safe error class,
    provider message ID, and final state.
  - Keep workflow success separate from delivery success.
- [x] Make delivery retries idempotent where a provider supports an idempotency key.
- [x] Mark an unprovable delivery result **uncertain** instead of sending it again.
- [ ] Add small event hooks from existing apps.
  - Hooks enqueue reviewed events; they do not run model work inside the app request.
  - External content stays untrusted and cannot approve its own action or create trusted memory.
- [ ] Convert current automations into paused Workflows and Triggers.
  - Preserve names, schedules, enabled intent, and action details where safe.
  - Require owner review of model, permissions, delivery, and schedule before enabling.
  - Do not silently activate a migrated automation.
- [x] Keep connector secrets in the encrypted Phase 1 credential path.

Current outbox evidence: 13 focused tests cover unique enqueue, two-worker claiming, privacy levels,
stable provider keys, restart-safe referenced summaries, bounded transient retry, permanent failure,
uncertain provider outcomes, idempotent recovery, non-idempotent crash quarantine, safe API fields, and
the rules that an uncertain delivery cannot be manually resent and a disabled connector secret never
reaches a provider. The selected outbox, record, and scheduler regression set is 41 tests.

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

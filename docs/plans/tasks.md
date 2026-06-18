# Phase 4 — tasks (`tasks.js` + `routes/tasks.py` + `services/task_nl.py`)

## Audit (2026-06-18)

Verified working (DO NOT rebuild): CRUD, priority, due dates, recurring (`repeat` + `advance` spawns the
next occurrence on completion), tags, projects, notes, subtask field (`parent_id`), manual reorder,
NL quick-add (`parse_task`: dates, #tags, ! priority, repeat), curated views (all/today/upcoming/
someday/history). UI loads with 0 console errors.

The backend is capable but the UI (96 lines) is thin: a flat list with check/delete/quick-add only.
Confirmed gaps: **no search**; **subtasks aren't shown** (the `parent_id` field exists but the list is
flat — no nesting, no add-subtask, no progress); **no way to edit an existing task** (priority, due date,
notes, project, tags, repeat) or reschedule it.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **tasks-1 Search.** GET `/api/tasks/search?q=` over title/notes/tags + a search box in the header.
  *Why: no way to find a task among many.*
- **tasks-2 Subtasks tree.** GET `/api/tasks/tree` returning top-level tasks with nested `subtasks` and
  done/total `progress`; UI nests subtasks under their parent, with add-subtask + an X/Y progress badge.
  *Why: `parent_id` exists but is invisible in the UI — subtasks are a core feature.*
- **tasks-3 Task editor + quick reschedule.** `task_nl.reschedule_date(when, today)` + POST
  `/api/tasks/{tid}/reschedule` (today | tomorrow | next_week | weekend | <weekday>); a detail panel to
  edit title/notes/priority(none/low/med/high)/due/tags/project/repeat. *Why: tasks are un-editable today;
  reschedule + priority levels are table-stakes.*

## Out of scope

Cross-device reminders (the reminders app owns notifications), location reminders, collaboration/sharing.

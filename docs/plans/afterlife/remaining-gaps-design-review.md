# remaining gaps design review

Status: both exact starters were approved by the owner on 2026-07-22 and their real Plan-board and
News implementations are complete with focused backend, JavaScript, and rendered browser evidence.
The token mark and incognito reference mark are implemented; only owner visual approval of the token
glyph remains outside the engineering gate.

## problem

### token usage mark

- **user:** the owner reading an Aide response;
- **situation:** the latest response has token usage but the count is visually easy to miss;
- **goal:** recognize the metric instantly without reading a label first;
- **obstacle:** the old text-only count had no stable visual anchor and its legacy action container was
  hidden in the current Aide shell;
- **successful ending:** one bare fragment mark and a short `12 tok` value remain visible in both themes
  and at phone width, with the full meaning available to assistive technology.

### Plan task board

- **user:** the owner planning and moving personal work;
- **situation:** Agenda and Week explain time, while Task stages exist in the database but the Plan board
  only reports counts;
- **goal:** see, add, order, filter, move, finish, and recover tasks in one Plan view;
- **obstacle:** a second Kanban store would split task truth, and a desktop-width horizontal board would
  fail on a phone;
- **successful ending:** Board is another view of the existing Task records and stages, with a deliberate
  one-stage mobile view and completion history.

### scheduled News

- **user:** the owner who wants a dependable private digest;
- **situation:** feed reading and generic Aide schedules exist separately, but there is no first-class
  News workflow joining source health, digest generation, Home, and optional Jarvis delivery;
- **goal:** configure sources once, preview the result, enable a schedule, and still receive useful links
  when extraction or a model fails;
- **obstacle:** feed auto-save behavior does not match the explicit Library-save contract and a broken
  source must not block every other source;
- **successful ending:** `Aide > scheduled > news` owns setup and operations, Home receives a brief, and
  every saved Library item remains an explicit owner action.

## assumptions

- Existing Task stages remain the source of truth: `backlog`, `next`, `doing`, `waiting`, and `done`.
- The board labels those stages `inbox`, `planned`, `in progress`, `blocked`, and `completed` without
  changing stored values.
- Calendar, Reminders, and Tasks remain separate records; Plan composes them but does not copy them.
- News is an Aide workflow, so operational setup belongs under Aide Scheduled. Library only receives an
  article or cluster after an explicit save.
- The supplied Kanban archive is an interaction and information reference, not a visual system to copy.
- Attachments and OPML are valuable follow-ups but are not required to close the first release.

## reference audit

Useful ideas retained from `kanban.zip`:

- real stage columns and task cards rather than summary counts;
- quick add at the point of work;
- due, priority, label, and project filtering;
- manual order, archive/history, and recovery-aware actions;
- a detailed editor that does not force every field onto the card.

Ideas rejected:

- its green visual language and component density;
- visible native selects, default checkboxes/radios, native date/time controls, browser confirmation, and
  native context behavior;
- a second standalone task database;
- horizontally clipped mobile columns;
- attachment and backup complexity in the first Plan-board pass.

## flow

### Plan

1. Open Plan and choose Board beside Agenda and Week.
2. Scan four active stages. Add a task from the board toolbar or a stage's quick-add row.
3. Filter by project, due state, or priority without changing the underlying task.
4. Select a task to inspect details. Drag it or use the explicit previous/next-stage actions.
5. Moving to completed sets `stage=done`; the task leaves the active columns and appears in Completed.
6. Restore from Completed to Inbox when needed.
7. On failure, keep the task in its last confirmed stage, announce the failure beside the board, and offer
   retry. Escape closes menus or details without discarding edits.

### News

1. Open Aide, Scheduled, then News. No source is fetched until News is enabled.
2. Review the small starter catalog or add a source. Test fetch and inspect title, category, language,
   recent items, and health before saving.
3. Choose a digest schedule and delivery destinations. Home is the default; Jarvis is available only
   after pairing.
4. Preview a realistic digest, including citations and explicit `save to Library` actions.
5. Enable News. The pipeline polls with conditional requests and per-source backoff, deduplicates and
   clusters entries, ranks diverse coverage, then publishes the brief.
6. If extraction or summarization fails, publish a link digest and mark summary as pending. If one source
   fails, preserve the rest and show its next retry.
7. Disabling News stops future polling without deleting sources or past briefs.

## screen inventory

### Plan starter

- app-owned Plan header with Home, current `task board` context, preview state, and preview theme;
- Agenda, Week, and Board sibling tabs;
- board toolbar with quick add, search, custom filters, and Completed;
- four active stage columns using existing Task records;
- selected-task detail pane with stage movement and completion;
- custom project menu and completed-history dialog;
- ready, loading, empty, partial, error, offline, disabled, and interrupted demonstrations.

### News starter

- app-owned Aide header and `scheduled / news` context;
- scheduled-work local navigation;
- source list with enable state and health;
- schedule and delivery configuration;
- cited digest preview with explicit Library-save actions;
- add/edit-source dialog with custom category, language, priority, and schedule choices;
- ready, loading, empty, partial, error, offline, disabled, permission, and interrupted demonstrations.

## screen specifications

### Plan board

- **purpose:** manipulate task stage and order without leaving Plan.
- **hierarchy:** Plan identity, sibling view, board toolbar, active stages, selected task.
- **layout:** one continuous four-column working surface and one contextual detail pane; lines mark real
  stage and pane boundaries instead of wrapping every region in a card.
- **components:** app shell, tabs, field, custom menu, custom choice buttons, task rows, detail pane,
  dialog, inline status.
- **actions:** add, filter, search, select, reorder, move, complete, restore, edit.
- **states:** usable records stay visible during refresh, partial, offline, and failed moves.
- **reflow:** at 620px and below, a custom stage tablist shows one column at a time; detail follows the
  board as a sheet and no page-level horizontal scrolling appears.
- **accessibility:** tasks are named buttons; columns are labelled regions; stage choice follows ARIA
  tabs; drag is never the only movement method; updates use a polite live status.

### News workflow

- **purpose:** configure and inspect one durable scheduled digest.
- **hierarchy:** Aide identity, scheduled context, enable action, sources, cadence/delivery, digest preview.
- **layout:** source operations own the flexible main area; compact settings and preview sit beside them
  on wide screens and stack in task order on small screens.
- **components:** app shell, local navigation, data rows, KOKUEN switches, custom radio groups, inline
  health, dialog, preview list, cited links, inline status.
- **actions:** add, test, edit, disable, delete, preview, enable/disable workflow, retry, save one item.
- **states:** source health is independent; a failed source never blanks the preview.
- **reflow:** local navigation becomes a contained strip; settings and preview stack; labels wrap and
  URLs truncate with accessible full values.
- **accessibility:** source switches have explicit names; choice groups support arrow keys; dialogs trap
  and restore focus; citation links and save actions name their article.

## component mapping

Reused contracts:

- app-owned shell, text action, icon action, primary action, tabs, fields, custom menu, custom choice
  group, KOKUEN toggle, toolbar, data row, local panel, dialog, inline status, and state message.

New variants:

- **stage column:** a labelled list of existing task rows with stable ordering and an inline add target;
- **task board row:** selectable task summary with title, one due signal, one priority signal, and a bare
  reorder handle; details remain in the pane;
- **source health row:** source identity, enabled state, last success or safe error, and next retry;
- **digest cluster:** one topic heading, terse synthesis, source links, and one explicit save action.

These variants add behavior that existing rows cannot express; they do not add a new visual language.

## state matrix

| state | Plan | News |
|---|---|---|
| loading | keep columns visible; mark refresh | keep saved sources and preview visible |
| empty | explain no active tasks; offer add | explain News is not configured; offer source |
| partial | preserve confirmed stages | publish healthy sources; list failed source |
| success | announce saved stage/order | show last brief and next run |
| warning | overdue or blocked copy | summary pending or source retry |
| error | restore last confirmed placement; retry | keep last digest; retry failed operation |
| disabled | unavailable movement states remain readable | sources retained; polling stopped |
| offline | browse cached tasks; queue no mutation | show last brief and source health |
| permission | not applicable for local tasks | Jarvis unavailable until paired |
| interrupted | draft and selection remain | unsaved source draft remains |

## responsive specification

- **stays:** app identity, Home, current context, primary action, selected stage/source, state feedback.
- **wraps:** toolbar search and secondary filters; digest source links.
- **stacks:** Plan detail and News schedule/preview on small screens.
- **collapses:** Plan shows one active stage; Aide local navigation becomes a strip.
- **scrolls:** each desktop stage may scroll internally; the page never scrolls horizontally.
- **moves:** Completed enters the overflow area before primary controls compress.
- **changes:** 32px desktop icon targets become at least 44px on touch layouts.
- **disappears:** low-priority counts may hide, but task/source names and status do not.

## interaction specification

- All custom menus use Up/Down, Home/End, Enter/Space, Escape, focus entry, and trigger focus return.
- Choice groups use arrow-key movement and expose `role=radio` with `aria-checked`.
- Board drag begins only from the handle, shows a stable insertion target, and commits after drop. A failed
  commit returns the row to the confirmed position and explains recovery.
- Stage movement is also available through labelled buttons in the selected-task pane.
- Quick add validates a non-empty title, preserves rejected input, inserts only after confirmation, and
  leaves focus ready for the next task.
- Source Test never saves. Save remains disabled until a valid URL and a successful or explicitly
  acknowledged test result exist.
- Enabling News summarizes source count, cadence, and delivery before completion.

## final copy

Plan: `agenda`, `week`, `task board`, `add a task`, `filter`, `completed`, `inbox`, `planned`, `in
progress`, `blocked`, `move back`, `move forward`, `mark complete`, `restored to inbox`, `move failed;
task stayed in {stage}`.

News: `scheduled`, `news`, `news is off`, `enable news`, `sources`, `add source`, `test source`, `last
success`, `next retry`, `every morning`, `home brief`, `jarvis delivery`, `preview digest`, `save to
Library`, `link digest ready; summary pending`, `one source failed; the rest of this brief is ready`.

## decisions

- Use existing Task stages instead of adding columns or a second data model. This keeps Tasks, Home,
  Calendar, and Plan consistent.
- Keep Done out of the active board and expose Completed as history. This preserves working width while
  keeping recovery obvious.
- Use a one-stage mobile board rather than horizontal overflow or squeezed columns.
- Put News under Aide Scheduled rather than create a ninth app or hide operations in Settings.
- Keep Home as the default delivery and Library save explicit.
- Treat drag as enhancement, never the only action.
- Defer task attachments and OPML until core stage and digest behavior is proven.

## QA acceptance

- No visible native select, checkbox, radio, date/time picker, or context menu.
- App identity appears once; no legacy `<app> / alles` crumb and no oversized repeated app title.
- Both starters contain only fake data, make no Alles API calls, load no remote asset, and modify no
  owner data. Real browser gates use an isolated throwaway `ALLES_DATA` root.
- Every visible control responds to a real pointer or keyboard action.
- Custom menus, tabs, radio groups, switches, dialog focus, Escape, and focus return match their ARIA
  contracts.
- Wide desktop, narrow desktop, phone, 200% zoom, dark, light, reduced motion, and keyboard-only layouts
  have no clipped text, overlap, invisible content, or horizontal page scrolling.
- Loading, empty, partial, error, offline, disabled, permission, and interrupted states preserve useful
  content and provide a recovery path.
- Focused API/unit regressions, 444 JavaScript regressions, and real rendered Plan/News gates pass.
- Real rendered Plan and News checks pass on desktop, phone, and 200% zoom with keyboard, dark/light,
  reduced-motion, page-error, console-error, and horizontal-overflow assertions.
- The final point-by-point design-system and anti-slop audit found no native product choices,
  duplicated/oversized app identity, hidden entrance content, clipped controls, hover movement,
  animated underlines, glow/bloom, fake window, generic marketing skeleton, or unhandled focus path.

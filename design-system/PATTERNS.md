# patterns

## shared shell

Every finished app owns its shell. Its app name and Home path live in the app header or the head of its
local rail; useful current context and actions align beside that identity. Do not stack the legacy
`<app> / alles` breadcrumb above an app-owned header. The interaction grammar stays stable while the
workbench below chooses one of four shapes. Theme belongs in Settings. The app picker is the cross-app
path; local panels never become a second global launcher. Legacy apps migrate only with their approved
redesign.

Show app identity once in the app-owned shell. The workbench starts with real task content; it never
repeats the app name as an oversized landing title. Any content heading names the active section,
document, date, selection, or task instead.

## list

Use for Tasks, Contacts, Books, Habits, Watchlist, Subs, and similar collections.

- one toolbar or filter row;
- one readable list with stable columns;
- optional quick capture at the bottom;
- details open inline or in a local context pane;
- empty and loading states preserve the list's alignment.

## timeline

Use for Calendar, Days, Journal history, Activity, and Health history.

- time controls share one tool row;
- the calendar or timeline owns the main work surface;
- secondary navigation remains local to the app;
- mobile converts local navigation to a horizontal strip or one active view;
- time grids may scroll inside their region, never the whole page sideways.

## workspace

Use for Docs, Files, Mail, Gallery, and Secrets.

- two or three aligned panes are allowed;
- left pane is app-local navigation;
- center pane owns the main task;
- right pane contains selection details or tools only when useful;
- each pane owns its scroll;
- mobile shows one pane at a time with an explicit back path and preserved selection.

## dashboard

Use for Money, Health summary, System, and Watch.

- key facts use comparable rows or one real data grid;
- use at most one primary visualization;
- supporting data remains visible and aligned;
- avoid a wall of independent cards;
- missing values hold their grid slot rather than shifting neighbors.

## settings

Settings is one product surface. Group by user intent, keep the current value visible, explain consequences before destructive or privacy-sensitive changes, and use custom KOKUEN choice controls. Theme and density live here, not in app headers.

## destructive action

Explain the object, scope, and recovery before confirmation. Default focus stays on the safe action. Do not rely on a red button alone. Show progress, success, and failure without losing the user's place.

## background or delayed work

Show accepted, running, waiting, needs approval, failed, stopped, and completed states. Work survives navigation. The owner can reopen the source task and understand what happened.

## provider-backed partial data

Render usable local or successful-provider data first. Name a quiet partial state without breaking the whole app. Retry only the failed region. Never replace good data with a full-page error.

## material rework gate

1. audit real behavior and existing components;
2. create a standalone KOKUEN HTML starter under `docs/mockups/`;
3. include realistic fake data, desktop/mobile reflow, interaction, and important states;
4. let the owner try that exact file;
5. wait for explicit approval;
6. migrate the real app in small, tested slices while preserving behavior.

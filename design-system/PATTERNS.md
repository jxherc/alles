# patterns

## shared shell

Every authenticated surface exposes one persistent universal navigation trigger. It opens one modal
sheet backed by the same 12-destination registry as the universal command: three primary spaces and
nine specialist apps. The trigger is never repeated in an app header. Local rails contain only useful
current context and app-specific actions. Do not show the legacy `<app> / alles` breadcrumb. Theme
belongs in Settings, and local panels never become a second global launcher.

Show app identity once in the local app shell. The workbench starts with real task content; it never
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

## material rework sequence

1. audit real behavior and existing components;
2. write the compact KOKUEN design map and state matrix;
3. use a standalone fake-data HTML starter under `docs/mockups/` only when it materially improves
   design reasoning or lets the owner compare a risky direction;
4. migrate the real app in small, tested slices while preserving behavior;
5. open and exercise the exact real application after the final change. A starter never substitutes
   for rendered production proof and is never an approval gate by itself.

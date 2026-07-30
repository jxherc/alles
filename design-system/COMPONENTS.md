# components

Components carry behavior, not decoration. Each contract applies in both themes and every supported viewport.

## universal shell

**Purpose:** make every space reachable without duplicating global navigation inside app headers.

- One persistent 52px structural rail contains one 44px navigation trigger on every authenticated
  product surface. The trigger opens the same modal navigation sheet from Home, Aide, Andromeda,
  every specialist app, and Settings.
- The sheet lists Home, Aide, and Andromeda first, followed by exactly Plan, Inbox, Docs, Files,
  Library, Health, Finance, Vault, and Server. The universal command uses this same registry.
- Opening the sheet makes the underlying workbench inert, moves focus to Close, traps Tab and
  Shift+Tab, supports Escape and scrim dismissal, and restores focus to the trigger.
- Local app headers never repeat Home or a second app picker. They contain app-local context and
  actions only.
- Never show the legacy `<app> / alles` crumb. It duplicates identity and makes the app look embedded
  in an older shell.
- Show the app identity once. Do not repeat the app name as a giant landing or workbench title below
  the shell. A content heading must name the actual section, document, date, selection, or task.
- The primary app-header row is 52px. The main context sits on the same baseline when useful; actions
  stay at the end of that row.
- Aide may use its task-context top bar, and workspace apps such as Docs and Files may align the app
  identity with their local rail. These are variants of the same contract, not exceptions.
- On small layouts, preserve the 52px identity row and use one additional 44px context or tab row only
  when the context cannot fit safely beside the identity.
- Theme stays in Settings. The shell is navigation, not a profile or appearance rail.
- Product modules retain local data and mutation authority. The shell owns only cross-app movement.

## text action

Use when the label is clearer than an icon. It has no visible container at rest. Hover changes tone only. Focus uses the focus token. Disabled state remains readable and exposes a reason.

## icon action

Use only for a widely understood action. Keep the SVG bare. The invisible hit area is 44px at every viewport. Add an accessible name and tooltip only when it adds meaning. No hover box, lift, or glow.

## primary action

One per screen. Use text and stronger tonal contrast, not a saturated filled pill. It must remain visible while the action is available and show progress without changing width.

## custom menu

- `role="menu"` with `menuitem` children;
- Up/Down moves, Home/End jumps, Enter/Space activates, Escape closes;
- focus moves into the menu and returns to its trigger;
- 4px outer radius, 2px row radius, 44px minimum row;
- disabled rows stay discoverable and cannot activate;
- never use a visible native select or context menu.

## custom choice group

Use buttons with `role="radio"` and `aria-checked`, or independent buttons with `aria-pressed`. Arrow keys move within radio groups. A checked state uses tone, type, and a small state mark, never color alone.

## tabs

Use for sibling views of the same data, not navigation to unrelated apps. Follow the ARIA tabs pattern. Keep labels visible, use type and tone for the selected state, and avoid decorative underlines or dots.

## toggle

Use only for an immediate binary setting. Use a custom button with `role="switch"` and `aria-checked`. Put the label and effect beside it. Do not use a native checkbox or a sun/moon theme switch.

## field

Visible label first, then control, helper or error below. Placeholder text is an example, never the label. Validation occurs at a useful time, preserves input, connects the error with `aria-describedby`, and says how to recover.

## search field

Use a real search input with a visible or accessible label. Search may expand only with transform or width behavior that does not repaint the surrounding layout. Escape restores the previous state and focus.

## universal command

Use one labelled modal dialog, one focused search input, and one listbox. The input owns
`aria-activedescendant`; group labels are presentational; every actionable result is a semantic button
with `role="option"`; and exactly one available result is active. Arrow keys move through results,
Home and End jump, Enter invokes, and Escape closes and restores focus. Keep idle, loading, no-match,
error, unavailable, and permission states inside the same surface. Ask-Aide and Andromeda actions name
their destination and effect before invocation.

## toolbar

Height: 52px. Align the title, filters, context, and one primary action on one baseline. Move low-priority actions into a custom overflow menu when space runs out. Never leave an unexplained blank toolbar region.

## data row

Interactive rows are at least 44px. A 36px visual row is allowed only for noninteractive dense data. Use a stable grid so titles, metadata, status, and values align across long and missing content. Hover changes surface tone only. Selected state uses raised surface plus semantic state.

## local panel

App-specific navigation or context only. It never repeats the universal launcher. It shares the app shell baseline, owns its scroll, and collapses to an inline strip, one active pane, or a drawer according to the workspace pattern.

## dialog and side panel

Use a dialog for a blocking decision and a side panel for continuing context. Label it, trap focus only when modal, restore focus on close, support Escape when safe, and prevent content behind it from becoming keyboard-accessible.

## inline status

Use short states such as `saving`, `saved`, `offline`, `partial results`, or `needs approval`. Keep status near the affected content and announce important asynchronous changes. Do not make a temporary toast the only record of important work.

## state message

- loading: skeletons match the final structure;
- empty: one sentence and at most one useful action;
- partial: preserve usable data and add one quiet status line;
- error: short cause plus retry or recovery action in place;
- offline: keep available local data visible;
- permission denied: state what needs permission and where to change it.

## new component contract

Document purpose, when to use, when not to use, anatomy, properties, variants, all states, pointer and keyboard behavior, content, sizing, overflow, responsive behavior, accessibility, approved/rejected examples, code mapping, and tests before adoption.

The machine-readable source for stable v5 contracts is `components/contracts.json`. Runtime behavior
lives in `static/js/kokuen.js`, with the custom single-select contract in `static/js/dropdown.js`.

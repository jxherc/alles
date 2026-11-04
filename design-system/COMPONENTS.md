# components

Components carry behavior, not decoration. Each contract applies in both themes and every supported viewport.

## universal shell

**Purpose:** make every space reachable without duplicating global navigation inside app headers.

- The app name is one 44px-minimum navigation trigger in the visible header. The same button moves
  with the active surface, including Aide's compact header, and opens the same modal navigation sheet
  from Home, Aide, Andromeda, and every specialist app. Settings stays a modal over the current app.
- The sheet lists Home, Aide, and Andromeda first, followed by exactly Plan, Inbox, Docs, Files,
  Library, Health, Finance, Vault, and Server. The universal command uses this same registry.
- Opening the sheet makes the underlying workbench inert, moves focus to Close, traps Tab and
  Shift+Tab, supports Escape and scrim dismissal, and restores focus to the trigger.
- Local app headers contain one app-name switcher plus local context and actions, never a second
  Home path or app picker.
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

Use only for a widely understood action. Keep the SVG bare. The invisible hit area is 44px at every viewport. Add an accessible name and tooltip only when it adds meaning. No lift or glow. A bare icon action changes tone on hover; an icon button (`.icon-btn`, such as an app's header gear) also takes the hover fill (`--k-hover`), the same feedback as the calendar arrows and files' icon buttons.

Set `data-kokuen-icon` to a name from `static/js/icons.js`; the shared runtime centers the 16px mark and preserves the owning control's accessible name. The runtime also upgrades legacy single-glyph close, delete, move, and send controls so dynamically rendered features do not fall back to mismatched text glyphs.

## primary action

One per screen. Use text and stronger tonal contrast, not a saturated filled pill. It must remain visible while the action is available and show progress without changing width.

In Alles the primary is the text action's shape plus one `--k-line-strong` line, full text color and weight 560; hover adds the raised surface. No filled block. A labelled region or dialog may hold its own primary (decision 0031).

## custom menu

- `role="menu"` with `menuitem` children;
- Up/Down moves, Home/End jumps, Enter/Space activates, Escape closes;
- focus moves into the menu and returns to its trigger;
- 12px surface radius, 8px row radius (12 minus the 4px inset), 44px minimum row, the raised fill
  and one float shadow (`--k-float`). every hand rolled menu takes this look from one rule in
  `revamp.css` ("one action menu look"); a new menu joins its lists. the picked row shows with text
  weight, never a second fill;
- disabled rows stay discoverable and cannot activate;
- never use a visible native select or context menu.

## custom choice group

Use buttons with `role="radio"` and `aria-checked`, or independent buttons with `aria-pressed`. Arrow keys move within radio groups. A checked state uses tone, type, and a small state mark, never color alone.

Which control does which job (owner, oct 28, decision 0050): 2 or 3 options flipped often are a
pill switch; a rating is a number row; 4 or more options, or a list that can grow, is the
dropdown (`dropdown.js`). Never a wall of chips or buttons for text choices: more than 3 text
choices is always a dropdown with type to jump (28.14). `tests/test_kit_part_two.py` lists every
group that keeps its look and why (color swatches, a rating, toggles that turn several things on,
navigation) and the walls still waiting for their dropdown; a new group fails it. Quick fills (model providers, rule presets)
are a dropdown with a placeholder that fills the form on pick; a server setting with more than 3
options or a model list is a dropdown, 2 or 3 a pill switch (28.29).

- pill switch: `<div class="k-pill-switch" data-kokuen-choice="switch" aria-label="unit">` with 2
  or 3 `<button>`s, one with `aria-checked="true"`. kokuen.js makes it a radiogroup with arrow
  keys; motion.js slides the round pill to the pick. 44px options, the pill 4px inside.
- number row: `<div class="k-number-row" data-kokuen-choice="rating" data-min="1" data-max="10"
  data-labels="easy,...,max" data-words="easy,,,,,,,,,max" aria-label="effort">`. 44px round
  numbers, end words centered under the number they name, a readout naming the pick, two rows of
  5 under 520px. listen for its bubbling `change` event (`detail.value`).

## stepper

A number a thumb nudges more than it types (weight, reps, glasses, minutes) is a stepper
(decision 0058, `static/js/stepper.js`): one 52px field with its own edge, a 44px minus inside the
start and plus inside the end, the value centered at role 22 semibold with tabular numbers.
`stepperHtml({ name, value, step, min, max })` builds it; `wireSteppers(root)` makes every
`data-kokuen-stepper="auto"` one step itself (buttons, arrow up and down in the field) and fire a
bubbling `change` (`detail.value`). Minus is off at the floor, plus at the ceiling; empty and "?"
count from the floor. Focus shows on the stepper's own edge only. A logger that keeps its own model
(the gym set logger) uses the markup with `auto: false`. A plain number with no common step is a
field with the numeric keypad, not a stepper. A number with a unit passes `unit` ("min", "g", "ml", decision 0067): the unit sits
muted right after the value inside the field, and the value is only as wide as what's typed.

## tabs

Use for sibling views of the same data, not navigation to unrelated apps. Follow the ARIA tabs pattern. Keep labels visible, use type and tone for the selected state, and avoid decorative underlines or dots.

The picked tab is one round pill that slides (decision 0050): a group of `[role="tab"]`, `.seg-opt` and the other items in motion.js's `ITEM` list gets `.has-pill`, and a row of them gets `data-pill-shape="round"`. The pill sits 4px inside the 44px target and is never clipped by a scrolling strip. A stack of rows (the settings nav) keeps the 8px row corner.

## toggle

Use only for an immediate binary setting. Use a custom button with `role="switch"` and `aria-checked`. Put the label and effect beside it. Do not use a native checkbox or a sun/moon theme switch.

Keep the 44px interaction target separate from its visible 42px by 24px rounded track.
Center the 16px circular knob vertically and move it horizontally between states. In
Settings, the on state also uses a stronger neutral knob. The hit-area rule must never
stretch the track into a circle or square. Settings, Home, setup, and Andromeda use this
same geometry; reduced motion removes the knob transition.

## field

Visible label first, then control, helper or error below. Placeholder text is an example, never the label. Validation occurs at a useful time, preserves input, connects the error with `aria-describedby`, and says how to recover.

One field (decision 0049): 44px, 12px between the text and the edge, the `--k-field` fill and a 1px ring. Focus recolors the ring to the dim neutral `--k-field-focus`; nothing else draws. Add a new field to the "one field" list in `revamp.css` or give it `.k-field`; a text field with zero side padding fails `tests/test_kit_page.py`. A wrapper-owned entry joins the bounded entry list in `kokuen.css` and shows focus on its own edge with the same ring. Long-form editors (docs source, notes, journal) take no box.

Use `data-kokuen-entry="compact"` for one-line search/capture entry and `data-kokuen-entry="autogrow"` plus `wireAutosizeTextarea` for short multiline capture or composition. Autogrow starts at 44px, follows content, respects its CSS maximum and viewport, and then scrolls internally. Do not apply either sizing variant to long-form editors. If a wrapper owns the field boundary, keep the inner input borderless and let `:focus-within` expose the focus state once.

## entry row

An add form is one entry row (decision 0052): `.k-entry-row` on the row, bare fields inside split
by a 1px divider, then one `.btn`. 4px padding on every side; the button is 44px with an 8px radius
and sits 4px from the top, end and bottom, 8px after the last field. No inline gaps or widths. On a
phone two or more fields stack and the button takes the last line.
A form error goes in the row as a child with `.k-entry-error` (hidden until it shows): it takes its own
full-width line under the fields and never narrows them. A server busy answer (503 `database_busy`)
reads through `busyText` in `util.js`, in the chosen language.

## date and time field

`.date-input` with `datepick.js`, never a native picker. `data-type="date"`, `"datetime"`, or
`"due"` (a date with an optional time: "add time" in the panel, "no time" in its footer), or
`"time"` (a time of day alone, "HH:MM", decision 0068: no calendar, the owner's 12 or 24 hour clock,
lowercase). Outside a
row it is the one field; inside an entry row it is bare. `joinDue` and `splitDue` map a due value to
a task's `due_date` and `due_time`.

## search field

Use a real search input with a visible or accessible label. Search may expand only with transform or width behavior that does not repaint the surrounding layout. Escape restores the previous state and focus.

## universal command

`Cmd-K` on Mac, the saved search shortcut, and `/` outside text entry open the same surface.
`/` never interrupts typing, dialogs, menus, or Aide composer slash commands. Docs editing keeps
its own key handling.

Use one labelled modal dialog, one focused search input, and one listbox. The input owns
`aria-activedescendant`; group labels are presentational; every actionable result is a semantic button
with `role="option"`; and exactly one available result is active. Arrow keys move through results,
Home and End jump, Enter invokes, and Escape closes and restores focus. Keep idle, loading, no-match,
error, unavailable, and permission states inside the same surface. Ask-Aide and Andromeda actions name
their destination and effect before invocation.

## toolbar

Height: 52px. Align the title, filters, context, and one primary action on one baseline. Move low-priority actions into a custom overflow menu when space runs out. Never leave an unexplained blank toolbar region.

## data row

Filled rows in a list or sidebar sit `--k-row-gap` (4px) apart and part by space, never by a divider (decision 0051). A new row list joins the "row list" rule in `revamp.css`; `.k-rows` / `.k-row` is the kit's own. Interactive rows are at least 44px. A 36px visual row is allowed only for noninteractive dense data. Use a stable grid so titles, metadata, status, and values align across long and missing content. Hover changes surface tone only. Selected state uses raised surface plus semantic state.

## local panel

App-specific navigation or context only. It never repeats the universal launcher. It shares the app shell baseline, owns its scroll, and collapses to an inline strip, one active pane, or a drawer according to the workspace pattern.

## dialog and side panel

Use a dialog for a blocking decision and a side panel for continuing context. Label it, trap focus only when modal, restore focus on close, support Escape when safe, and prevent content behind it from becoming keyboard-accessible.

A dialog that only shows something (the steps behind an Aide reply) is a view dialog (`view` in `dialog.js`): one title, the content, one close button, no cancel. The content scrolls between the title and the close button, and focus returns to the control that opened it.

## inline status

Use short states such as `saving`, `saved`, `offline`, `partial results`, or `needs approval`. Keep status near the affected content and announce important asynchronous changes. Do not make a temporary toast the only record of important work.

One notice rule (`notice.js`): a confirmation clears itself after a while (`dismissAfter`), an error stays until its close button is used (`errorNotice`). Both have a close button; neither is stuck.

Controls carry no native `title` tooltip. A title that is a control's only name becomes its `aria-label` (`kokuen.js` `dropNativeTooltip`).

## state message

- loading: skeletons match the final structure;
- empty: one sentence and at most one useful action;
- partial: preserve usable data and add one quiet status line;
- error: short cause plus retry or recovery action in place;
- offline: keep available local data visible;
- permission denied: state what needs permission and where to change it.

## hidden

`el.hidden = true` always hides. `kokuen.css` owns one `[hidden] { display: none !important; }`, so a
class that sets `display` can't show a hidden element any more. Don't add a `.x[hidden] { display:
none }` patch (`test_the_hidden_attribute_always_hides_from_one_rule` fails on one). An element that
must stay laid out while hidden says so with its own higher `!important` rule beside it: the vault's
unlock error keeps its line (`#vault-unlock-error[hidden]`), and the app drawer and its scrim keep
showing for their closing slide (`#app-drawer.is-closing`).

## new component contract

Document purpose, when to use, when not to use, anatomy, properties, variants, all states, pointer and keyboard behavior, content, sizing, overflow, responsive behavior, accessibility, approved/rejected examples, code mapping, and tests before adoption.

The machine-readable source for stable v5 contracts is `components/contracts.json`. Runtime behavior
lives in `static/js/kokuen.js`, with the custom single-select contract in `static/js/dropdown.js`.

## kit page

`static/kit.html` shows every universal piece in its states, light and dark (`?theme=light`). It loads the same stylesheets as `index.html` in the same order (a test keeps them equal). `tests/pw_kit_rules.py` checks it, and every route, in webkit at desktop, ipad landscape, ipad portrait and phone. A new piece goes on the kit page first.

## busy edge

While work runs, a rounded box shows it on its own 1px edge (decision 0053): `.k-busy` with
`data-busy="true"` (the aide composer and aide code's entry are wired already). The tone turns
slowly around the corners; reduced motion shows a steady brighter edge. Never a line laid over the
edge, a glow outside it, or a stripe on one side.

## resizable rail

Every app sidebar resizes with one handle (decision 0054, `rail_resize.js` `makeResizableRail`): a
12px `role="separator"` strip on the trailing edge with a 32px grab for a finger, drag by mouse, pen
or touch, arrow keys (shift for 3rem), home and end, double click back to the app's width. The width
is in rem and saved per browser; phones and stacked tablet layouts get no handle.

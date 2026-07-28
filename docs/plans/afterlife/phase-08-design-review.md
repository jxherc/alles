# Afterlife Phase 8 specialist apps - design review

- **Status:** exact starters approved by the owner; real interface implemented and browser-verified
- **Parent design:** [`design.md`](design.md)
- **Phase tracker:** [`phases/phase-08-specialist-app-consolidation.md`](phases/phase-08-specialist-app-consolidation.md)
- **Reviewed:** 2026-07-18 against the current implementation, tests, and official integration sources

## Product brief

Phase 8 is for the owner who uses Alles throughout the day and currently has to remember which small
app owns a related action. The job is to reduce app switching without flattening specialist records or
turning Home into a dashboard.

The intended experience is compact, calm, connected, and quick to scan. The desktop layout can use two
or three purposeful panes. Mobile turns those panes into one vertically ordered work surface, with the
local rail becoming a labelled horizontal scroller rather than a second page axis. Motion is limited to
state feedback and already-visible transitions. Content is visible without animation.

The shared visual idea is a **local workbench**: one treated product header, one app-specific rail, and
one primary working surface. The rail changes meaning by app rather than repeating generic cards:

- Plan uses time and commitment views;
- Inbox uses mailboxes and people context;
- Library uses material type and reading state;
- Health uses today, trends, and history;
- Finance uses ledger sections and migration state.

This is an application interface, not a marketing page. It keeps the existing KOKUEN tokens, system
font, compact typography, restrained tonal surfaces, and bare semantic marks. It does not introduce a
new font, remote image, icon pack, glow, decorative grid, floating card, entrance reveal, or generic
hero composition.

## Current implementation map

| New product | Existing views | Existing authority kept in Phase 8A | Composition gap |
| --- | --- | --- | --- |
| Plan | Calendar, Tasks, Reminders | `calendar_events`, `tasks`, `reminders`; current Calendar, Tasks, and Reminders APIs | one date-aware work surface and compatibility routing |
| Inbox | Mail, Contacts | cached/provider mail data and contact tables; current Mail and Contacts APIs | sender and compose context without merging records |
| Library | Books, Read/Watchlist, Andromeda News | `books`, `read_items`, `read_feeds`; current Books and Read APIs | explicit save from News and one material/state index |
| Health | Health, Habits | `health_entries`, `habits`, `habit_logs`; current Health and Habits APIs | today rhythm beside measurement history |
| Finance | Money, Subscriptions | existing Money and Subscription rows until the Actual cutover gate | additive currency/import sidecar, safe imports, and one canonical ledger |

The implemented shell publishes exactly five specialist destinations. Their overview workbenches
compose the existing APIs without merging their records, and compatibility routes mount the proven
legacy screens inside the requested group subsection. Finance includes the additive currency/import
foundation and managed Actual boundary; legacy ledger rows become read-only only after a staged,
reconciled cutover.

## Directions considered

### 1. Rename the current links only

Rejected. A group name over unchanged separate screens would not reduce context switching and would
make the completion claim dishonest.

### 2. Embed or visually stack the old screens

Rejected. The existing screens carry their own headers, loading ownership, and layout assumptions.
Stacking them would duplicate controls, create nested scrolling, and make mobile and keyboard behavior
fragile.

### 3. Compose new group views over existing APIs

Chosen. Each group gets one small controller and one scoped view. Existing tables and API behavior stay
authoritative in 8A. Old hosts, view names, and deep links become compatibility entries into the
corresponding group and preserve the requested subsection. This keeps the data migration independent
from the navigation change.

## Screen decisions

### Plan

The default is a date-aware agenda, not a month-calendar-first screen. A narrow date rail selects today,
the next seven days, or backlog. The main list interleaves events, due tasks, and reminders in time
order while preserving their type and specialist actions. A secondary lane shows unscheduled tasks and
quick capture. Month and task-board views remain available inside Plan.

### Inbox

The default is a real three-pane mail workflow when space permits: mailbox rail, message list, and the
selected message. A collapsible people context area shows the existing contact, related messages, and
compose actions. Contacts is not turned into mail metadata and mail bodies are not copied into contact
rows.

### Library

The default is a mixed reading queue with explicit material marks for article, saved news, and book.
Type, unread/reading/done, favorites, and tags are typographic filters, not a field of status pills.
Andromeda News gains an explicit Save to Library action. Merely appearing in a feed or result list does
not create a Library item.

### Health

The default pairs today's habit rhythm with a chronological health log. Measurements remain visibly
distinct from habit completions. Sensitive context rules remain unchanged: Project selection never
adds health records to Aide, and any future AI use requires an explicit grant.

### Finance

The default is a ledger workbench with Overview, Accounts, Transactions, Budgets, Subscriptions, and
Import. It must show whether Actual is unavailable, staging, ready, or canonical. Money and
Subscriptions compose only after additive schema parity. The UI never suggests bank sync is available
for a named bank until the current provider/account eligibility is proven.

## Shared control and state rules

- Every toggle uses the universal KOKUEN switch: rounded track, circular knob, `role="switch"`, true
  `aria-checked`, Space/Enter behavior, a 44-pixel target, focus visibility, and a real disabled state.
- Choice menus and segmented choices use custom KOKUEN buttons/listboxes or radio semantics. No visible
  native select, checkbox, radio, or context menu is allowed.
- Loading keeps the workbench structure visible. Empty, partial, offline, error, and disabled states
  explain what remains usable and offer a direct recovery action when one exists.
- Destructive and import actions require preview. Imports expose duplicate decisions and an undo
  receipt before they can change the canonical ledger.
- Compatibility routes keep the original intent. `calendar`, `tasks`, and `reminders` open the matching
  Plan subsection; equivalent rules apply to the other groups.

## Responsive and accessibility review

- Desktop starts at a compact three-pane layout only where the content needs it.
- Narrow screens use one vertical page axis. The local rail and group navigation own their labelled
  horizontal scrolling; the main and detail regions remain in document order without browser history
  as the only path.
- Text can reach 200 percent without horizontal page scrolling. Data tables may use a labelled internal
  scroller or change to a record layout.
- Keyboard order follows the visible workflow. Roving tabs and listboxes support arrow keys; Escape
  closes transient layers and restores focus.
- Current selection is conveyed by type, weight, and surface, not color alone. Status text remains
  readable in both themes.
- Reduced motion removes non-essential transitions. No content begins hidden or depends on a reveal.

## Starter approval boundary

The five standalone starters use fake data and local-only interactions. They may demonstrate navigation,
filters, custom choices, switches, import preview, loading, empty, partial, offline, error, and mobile
reflow. They must not call an Alles API or change owner data.

The real specialist interfaces stay unchanged until the owner explicitly approves these exact starter
directions. Approval of an older Phase 6 or Phase 7 starter does not count.

## Design-law preflight

The proposed screens were checked against the full project design law before starter construction. The
direction avoids the listed generic marketing skeletons, default font rotation, blue-purple gradients,
glows, card hover lifts, icon tiles, decorative pills, fake app windows, hidden entrance content,
clipped type, ragged comparison columns, native controls, dead interactions, and default sun/moon
toggle. The signature is functional composition and data specificity, not decorative novelty.

The rendered starter gate must repeat the full point-by-point check at desktop, mobile, both themes,
200 percent zoom, keyboard-only use, and reduced motion before approval is requested.

## Rendered starter gate

Completed on 2026-07-18 against the exact five starters in
[`docs/mockups/afterlife-specialists/`](../../mockups/afterlife-specialists/):

- all five rendered at 1440 by 900, 390 by 844, and a 720 by 500 zoom-sized viewport;
- dark and light semantic tokens, 12-pixel minimum helper text, 44-pixel visible targets, and at least
  7:1 page text contrast passed the automated gate;
- tabs, listbox states, universal switches, custom checkbox semantics, dialogs, Escape, focus return,
  fake import preview/receipt/undo, and current-group visibility passed pointer and keyboard checks;
- no native select, checkbox, radio, file input, native context menu, remote asset, API request, browser
  error, page overflow, or motion-required content was found;
- the rendered review found and fixed whole-page mobile expansion, a root-scoped theme defect, a
  sticky footer covering live content, undersized metadata, noncanonical color approximations, and
  detail text clipped by an over-broad `max-content` rule.

The full design law was reread item by item after those fixes. The starters contain no marketing hero
skeleton, font import, gradient/glow, floating or hover-lift card, icon tile, pill metadata field,
fake-window prop, background grid, decorative rule, all-around shadow, entrance reveal, cut text,
ragged comparison layout, button movement, sun/moon switch, native choice control, dead control, or
unearned logo. Existing KOKUEN structure and real specialist data roles provide the signature; the UI
uses pane seams only for real information boundaries and keeps every visible interaction functional.

The owner explicitly approved these exact starters on 2026-07-18. The real implementation was then
checked at desktop and mobile widths in both themes with keyboard-only cutover and rollback previews,
focus return, reduced motion, 44-pixel controls, the type floor, compatibility routes, visible errors,
responsive overflow, and clean console output. The same point-by-point design-law audit remains part
of the final Phase 8 completion gate.

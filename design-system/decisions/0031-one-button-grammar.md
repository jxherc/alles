# one button grammar

## context

A click-through audit of every route found the same action drawn five ways: the old `.btn` box with 12px tracked caps, Docs' bordered buttons, Files' raised tile, Plan's light filled block and Settings' outlined save. Several screens showed three to five boxed buttons at once. Legacy `:focus` rules on about twenty fields still repainted all four borders, so decision 0030's single bottom line came back as a box on Mail, Tasks, Calendar, Money, Files, Photos, Activity and Journal. Overview columns stacked 16px insets on top of the page gutter, so text in one column started at 24, 40, 48 and 52px.

## decision

- Text actions (`.btn`, `.act-btn`, Docs, Server cards, Mail provider links) have no box at rest. Hover changes tone. 44px tall, 13px, 0 12px, one line.
- The primary action is the same shape plus one `--k-line-strong` line, full text color and weight 560. It replaces the filled blocks in Plan, Finance and Files. One per surface; a labelled region or dialog counts as its own surface.
- Filter chips and segments stay bare until selected, then use the raised surface, strong line and weight (decision 0019). No accent fill or tint for ordinary selection.
- Selected tabs use tone and weight only. The shared `selected` state no longer paints a tile on `[role="tab"]`.
- Legacy text fields keep their resting boundary; their `:focus` rules no longer touch `border-color`. Legacy search and quick fields (`.cal-quick`, `.act-search`, `.cal-side-search`, Files search, Journal fields, Plan board fields) use the compact bottom rail.
- Specialist workbench columns carry no inset. The column gap separates them, so each column's text starts on its own edge and the first matches the page gutter. Inline text actions at a content edge shift left by their padding so the label, not the hover box, lines up.
- Clickable date grids (month calendar, mini calendar, journal heatmap) follow the grid pattern through `static/js/grid_nav.js`: one tab stop, arrow keys, Enter or Space.
- KOKUEN tokens are also defined on `:root`, so shared rules resolve in dialogs and menus mounted outside a surface.

## verification

`tests/pw_ui_audit.py` (browser gate `ui-audit`) visits every route on desktop and phone in both themes, at 320px and at 200% zoom, hovers and clicks every reachable button, measures what opens, and scores the KOKUEN checklist, the browser-measurable WCAG 2.2 AA criteria and the Vercel Web Interface Guidelines rules that fit the house style.

## chips pass (2026-10-20)

The groups the balance pass left boxed are bare at rest now: Server's search provider, results per
search and fact-check choices, Activity's sources and range, Journal's moods and Library Read's
filters. Each option has a transparent line, hover takes the hover tone, and the picked one gets the
raised surface, strong line and weight. Each row moves back by its padding so the first label sits
on its column (1px off for the transparent line, like the other pull-backs).

Activity's sources are toggles that all start on, so a raised "on" boxed the whole row again. On is
full text; off is muted and struck through, so it doesn't rest on color alone. `.act-chip` is left
out of the shared `selected` tile for the same reason. Read's "feeds" toggle sits 12px apart from
the four filters, since it isn't one of them.

The segmented controls followed: the shared `.seg` (Calendar's views, persona mode, the per-app
settings popovers, CardDAV sync and Vault's template fields), the theme editor's `.te-seg` (font,
density, background, harmony, a book's shelf), the clock choice in language settings, appearance's
mode row, the theme presets and Memory's policy. No outer line or dividers; words pack from the left
with 12px each side and every option is 44px tall. Where a group stacks under its label it moves back
by the padding; where it ends a row (the clock choice, Memory's policy on desktop, Calendar's views on
desktop) the box keeps its place, as the balance pass did for right-aligned rows.

Read's filters re-render on every pick, which dropped keyboard focus to the page. The pressed chip
gets focus back after the re-render. On a phone Activity's search takes its own line from the column
edge instead of floating right.

# one field style

## context

The balance pass left forms that drew two field styles side by side. The shared date picker
(`.date-input`) was a filled box with a 1px frame while the text field (`.settings-input`) and the
custom select beside it were bottom underlines, so Plan's reminder form, Countdowns' and
Subscriptions' edit rows, Calendar's event editor and Gallery's filter mixed the two. Money went the
other way: an old rule boxed its text inputs "to match the date picker", which left the dropdowns as
underlines in the new transaction, transfer, rule and schedule forms.

## decision

- Form fields use the underline: no fill, no side or top line, one `--faint` bottom line that turns
  `--muted` on hover or while open. This is the `.settings-input` style the shared text field and
  custom select already had, and the one form footers already forced on the date picker.
- `.date-input` itself is now that field, with no inner padding, so its text starts on the same edge
  as the fields beside it. On focus its own bottom border turns the field-focus color (decision 0045
  replaced 0030's painted line); forced colors keep the Highlight outline.
- Money's text inputs drop their box in the transaction, transfer, rule and schedule forms.
- Long-form editors (Calendar's description, Memory's instructions) keep their workspace boundary,
  as decision 0026 says. Search fields are their own one-field forms and are not changed here.

## other leftovers fixed in the same pass

- A text action that wraps to start a row puts its label on the column edge. Docs' empty actions
  move the row back by the padding and step the first action in again, so this holds at any width
  without measuring the wrap. Gallery's phone header gives search the first line and starts the
  actions row with filter.
- Phone actions keep their own width instead of splitting the row (Mail's refresh and compose,
  Settings → Home's reset and save). Plan's reminders header starts with "enable notifications".
- Countdown empty text spans the grid; usage and Journal empty text starts on its heading's edge; a
  Settings hint keeps 12px above the field label or box under it.
- Finance imports: the panel's 16px grid gap already spaces its notes, so a note's own 24px bottom
  margin made 40px gaps. Notes keep 8px (24px total), which lifts the file button 32px and keeps it
  on screen at 200% zoom.

## verification

Rendered positions were measured with `getBoundingClientRect` on an isolated server at 1440, 390,
320 and 720@2x (200% zoom), dark and light, at rest, on hover and with keyboard focus: no control
moves between states, and every changed row lines up on its column edge.

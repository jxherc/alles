# row gap 4px, control gap 8px, one line per edge

amends 0041 ("rows sit 2px apart").

## context

- 28.12 and 27.24: the settings sidebar's hovered row touched the picked one. 0041 set a 2px row
  gap, which isn't on the spacing scale, and the oct 27 fix went into docs only. the settings
  nav had 0, mail folders and photos about 1px, aide sessions 1px margins, task and record rows
  2px.
- 28.29: the server's answer model choices were buttons with no gap between them, built by a
  local helper.
- 28.30 and 28.32: the server cards drew a bottom line and every fact row drew its own, so two
  lines stacked with nothing between them.

## decision

- `--k-row-gap: 4px` (`kokuen.css :root`). one rule in `revamp.css` ("row list") names every
  stack of filled rows: settings nav, mail folders and rows, photos nav, skills rail, aide
  sessions and tool links, tasks, records, activity, contacts, vault entries, health rows and
  the kit's `.k-row`. rows lose their own margins and top and bottom dividers; the next row
  starts 4px down. a new row list joins that rule.
- `--k-control-gap: 8px`: separate controls sit 8px apart across and down. 0 only inside one
  shared track (a tablist, a radiogroup, a segmented control, a pill switch, a number row).
- every group of separate controls sets `gap: var(--k-control-gap)`. the first pass added the
  token but nothing used it: 49 action bars, form rows and dialog button rows in `style.css`, 22
  inline rows in `index.html` and 4 in js templates each wrote their own gap (0.25rem to 0.45rem,
  4.4 to 7.9px at the 109% root), so 20 groups on 9 screens still touched (28.29, second pass).
  icon toolbars whose buttons paint nothing (task, transaction and message actions) keep 4px;
  the rendered check only counts painted controls.
- a dropdown trigger's chevron sits `--k-chevron-end` (12px) from its end, the same as the text
  start; the label stops a control gap before it. a field joined to the one before it by a 1px
  left edge moves it in by that pixel (28.02).
- one boundary per edge: rows part by space, a section by one line or by space. a row never
  draws a line where its card already draws one. the server fact and service rows lose their
  lines.

## checks

`tests/pw_kit_rules.py` (webkit, 4 sizes, both themes):
- a picked, filled row has no clickable neighbor under 4px away;
- no two separate painted controls under 8px apart, across or down, outside one track;
- a dropdown's chevron ends within 1px of the inset its text starts at;
- no two parallel lines under 24px apart with nothing between them (a boxed card's edge is a
  box, not a divider).

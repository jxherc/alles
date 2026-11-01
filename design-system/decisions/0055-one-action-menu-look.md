# one action menu look

## context

about 15 menus were built by hand, each with its own corner, inset, row height and shadow: the
composer's context menu had an 8px surface with square 32px rows and no inset, the docs menu an 8px
surface with 6px rows, the plan board an 8px inset, the aide menus a flat panel with no shadow. the
owner's 28.19 report showed a countdown menu that looked nothing like the reminders one.

## decision

- one rule in `revamp.css` ("one action menu look") draws every action menu and the dropdown
  panel: the raised fill, a 12px surface radius, a 4px inset, one float shadow (`--k-float`), no
  border line of its own.
- rows are 44px with an 8px radius (12 minus the 4px inset) and 12px side padding. hover, keyboard
  focus and the dropdown's active row share one fill.
- the picked row (a checked mode, project or harness, the dropdown's current value) shows with
  text weight, never a second fill, so it never touches the hovered row.
- danger rows keep the danger color on hover.
- a new menu joins the rule's two lists; `tests/test_kit_part_two.py` checks the list.

## checked

webkit at 1280, 1180, 820 and 390 wide, dark and light: every menu that opens on throwaway data
(aide more, permissions, add context and its app links, slash, a message's more, aide code's
harness, docs more, plan board, countdown by tap and by keyboard) measured 12px radius, 4px inset,
44px rows with 8px corners and the float shadow.

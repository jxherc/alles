# pick several is the dropdown

## context

the ux laws say "pick several (muscle groups, tags, people)" is a dropdown with checkmarks and the
picks as text in the trigger. `dropdown.js` only picked one, so screens built chip walls instead
(activity had 9 source chips and a 4 button range).

## decision

- `dropdown.js` gets a pick-several mode: `data-multiple="true"` or `populateMultiDropdown(el,
  options, values)`. the listbox is `aria-multiselectable`, each picked option shows a check mark
  (the mark alone shows the pick, no filled row), enter, space or a click toggles and the list stays
  open, typed letters open it at the match, escape and tab close it.
- the trigger reads the picks joined by ", " (ellipsis when long), or its placeholder when none.
- `el.values` and `getDropdownValues(el)` read and write an array; `dataset.value` keeps the picks
  joined by ";" (the option format already reserves ";").
- first use: activity's "what to show" (pick several) and its range (pick one).

## checks

- `tests/js/dropdown_multi.test.mjs`: trigger text, keyboard toggling that stays open, placeholder,
  array values, single mode unchanged.
- `tests/test_ui_controls.py`: activity filters use the kit dropdown, no chips.

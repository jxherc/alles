# days — audit findings (2026-06-18)

Drove `days.localhost:8799`. Real seeded events render in three sections (today / upcoming / counting up):
Birthday (today), FutureMonthly (upcoming), etc. Zero console errors. Add/edit/delete/pin all work.

## The reported bug (confirmed)
`_render()` had a special branch: when `_editing` was set it rendered the edit card **first**, then every
other card as a flat, section-less list. So clicking "edit" on a card in `upcoming` or `counting up`
**yanked it to the very top of the grid** — `edit-before.png` vs the RED run showed the editing card at
index 0 with no section header before it. Exactly the user's "when you edit a day the ui is buggy where it
appears in the first grid even though it's on the second or third".

## Fix (`days-ui-1`)
Drop the special editing branch; render the normal `sections` layout always, and within each section swap
`_editCard(e)` for `_card(e)` only for the row whose `id === _editing`. The edit card now stays in its own
section and position. No backend change.

**Verify (`pw_days_edit.py`, 7 assertions, RED→GREEN, screenshots):** multiple_sections, picked_card_not_first,
edit_card_appears, edit_card_same_id, **edit_card_in_place** (same index, not yanked to top),
**section_header_before_edit** (still under its section), zero_console_errors.

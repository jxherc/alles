# settings are grouped by what you're doing

## context

owner, oct 28 (28.28): "setting is not organized at all, genuinely organize everything in a
completely new way, invent a new way of organization". the settings nav had 20 panes in 5 groups
named after the code ("you", "aide", "apps", "connections", "this alles"): models sat 9 rows away
from personas and voice, search credentials sat next to personal records search, and the server
panels had no entry at all. the owner was asleep for this run, so three layouts were built as
working demos and one was picked; the owner can flip to any of them.

## decision

- `static/js/settings/organization.js` holds four layouts as data. each lists the nav groups and
  the panes in them; `applyOrganization` moves the existing nav buttons under fresh group headings
  (their listeners stay), so no pane is rebuilt and nothing can get lost.
  - **by what you're doing** (default, picked): you · how aide answers (models, personas, voice,
    chat display) · what aide knows (memory, web search, personal records, andromeda) · what aide
    does on its own (background checks, automations, patterns) · accounts and connections ·
    safety and this alles (password, backups, the server, about).
  - **by how often**: every day · now and then · once, at setup · rarely.
  - **by what it changes**: this device · aide · your accounts · apps · this alles.
  - **classic**: the old grouping, kept so nothing the owner learned is gone.
- general › setup › "settings layout" (a kit dropdown) flips the layout; it's kept per device.
- the server app gets one entry in settings ("server", under safety and this alles); it closes
  settings and opens the server's overview. its panels stay in the server app.
- `scripts/settings_homes.py` proves every pane, the server entry and every first run setup step
  has exactly one home in every layout; `--table` prints the inventory (what each pane is for, how
  often it's opened, how many controls, its home in each layout).

## why "by what you're doing"

- it matches the owner's complaints: models, personas and voice now sit together ("model
  management is just a complete mess"), and search credentials sit with what aide knows instead of
  next to unrelated panes (28.31).
- frequency changes over time (a new install opens "once" panes every day for a week), so groups
  by how often move under the owner's hand.
- "by what it changes" ends up close to the code's folders, which is what the owner rejected.

## checks

- `python scripts/settings_homes.py` exits 0; `tests/test_settings_homes.py` runs it.

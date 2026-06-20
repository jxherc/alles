# ui-4e — rules + accounts into settings

Dropped the **rules** and **accounts** buttons from the mail toolbar (`static/index.html`) and re-homed both
into the mail-settings cog:

- `static/js/appsettings.js`: added an **`action`** field type (renders a full-width `.aps-action` button that
  closes the popover and calls `window[act]()`); the `mail` spec gains two actions — **accounts**
  (`_mailAccounts`) and **rules & vacation responder** (`_mailRules`).
- `static/js/mail.js`: exposes `window._mailAccounts = accountsPanel` / `window._mailRules = rulesPanel`
  (the existing panels are unchanged — they render into the reading pane as before).

Toolbar is now just: search · refresh · compose · ⚙.

Tests: `tests/test_mail_ui.py::RulesAccountsInSettings4e` (5) + `docs/evidence/ui-4e/verify.py` (both buttons
gone from the toolbar, settings popup carries accounts + rules actions, clicking runs the hook + closes the
popover, 0 console errors).

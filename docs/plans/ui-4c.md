# ui-4c — centered search + left account picker + "all accounts"

After the sidebar move (4b) the head is `[☰] [account] [search……] [actions]`:

- **Account picker pinned left** — `.mail-account-select { flex-shrink: 0 }` (and narrowed to
  `min(220px,30vw)`), sitting at the head's left after the toggle.
- **Search centered with a cap** — `.mail-head .mail-search { flex: 1 1 auto; max-width: 560px; margin: 0 auto }`
  so it fills the middle but the input itself stays centered and capped.
- **"all inboxes"** — already guaranteed by `syncAccountSelect` (`if (_accounts.length > 1) opts.push({value:'all',
  label:'all inboxes'})`); confirmed/locked.

Tests: `tests/test_mail_ui.py::SearchAndAccounts4c` (3) + `docs/evidence/ui-4c/verify.py` (account left of
search, search before actions, max-width 560 + auto margins + grows, dropdown present, 0 errors).

# ui-4d — compose, properly

`static/js/mail.js` + `routes/mail.py` + `static/style.css` (dirty-close confirm + undo-window send already
existed):

- **Chip To/Cc/Bcc** (`_initChipField`): type address + space/comma/Enter/blur → chip; backspace on empty
  pulls the last chip back; invalid → red chip. Each field mirrors into a hidden `#mc-to|mc-cc|mc-bcc` so
  send/schedule/draft-save/dirty-detection are unchanged. **Cc/Bcc** hidden behind add-Cc / add-Bcc toggles.
- **Autocomplete** (`_loadAddrBook`): merges `/api/contacts` + the new **`GET /api/mail/recipients`**
  (distinct recent correspondents from the mail cache — name + address, substring filter). ↑/↓/Enter/click.
- **Schedule = date picker + time**: replaced the manual `YYYY-MM-DDTHH:MM` box with a `date-input`
  (`initDatePicker`) + an `HH:MM` field; first click reveals them, second assembles `send_at`.
- Bigger compose area (body 220→300px, panel 620→680px).

Tests: `tests/test_mail_recipients.py` (6, backend) + `tests/test_mail_ui.py::Compose4d` (6) +
`docs/evidence/ui-4d/verify.py` (11 DOM checks: chips on Enter/comma, mirror to hidden, backspace pull-back,
Cc toggle, autocomplete dropdown, schedule date+time, dirty-close confirm, 0 errors) + `findings.md`.

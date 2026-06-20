# ui-4d — compose, properly

The compose already had dirty-close confirm + an undo-window send. Added the missing "proper compose" pieces
in `static/js/mail.js` (+ `routes/mail.py`, `static/style.css`):

- **Chip (token) To/Cc/Bcc** — `_initChipField` turns each recipient row into chips: type an address + space /
  comma / Enter / blur → a chip; backspace on an empty input pulls the last chip back for editing; invalid
  addresses get a red chip. Each field mirrors to a hidden `<input id="mc-to|mc-cc|mc-bcc">` so send /
  schedule / draft-save / dirty-detection keep working unchanged. **Cc** and **Bcc** are hidden behind toggle
  buttons (add-Cc / add-Bcc).
- **Autocomplete** — `_loadAddrBook` merges `/api/contacts` + the new **`GET /api/mail/recipients`** (distinct
  recent correspondents from the mail cache, name + address, substring-filterable); typing shows a dropdown
  with ↑/↓/Enter/click selection.
- **Schedule = a real date picker + time** — replaced the manual `YYYY-MM-DDTHH:MM` text box with a
  `date-input` (`initDatePicker`, reused from calendar/days) + an `HH:MM` time field; the button reveals them
  on first click and assembles `send_at` on the second.
- **Bigger compose area** — body min-height 220→300px, panel 620→680px.

Verified end-to-end by `verify.py` (11 DOM-level checks: chips form on Enter/comma, mirror to hidden,
backspace pulls back, Cc toggle, autocomplete dropdown with a mocked recipient, schedule reveals date+time,
dirty-close confirm, 0 console errors) + the 6 backend `test_mail_recipients` tests. **Screenshot note:** as
in 4b, the mail layout only paints with a connected account (no IMAP creds in the throwaway test env), so a
populated screenshot isn't capturable here; the compose markup, behaviour, and styling are confirmed by the
DOM assertions.

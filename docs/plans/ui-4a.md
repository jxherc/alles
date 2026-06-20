# ui-4a — mail toolbar cleanup

`static/index.html` (mail-head) + `static/js/mail.js` + `static/js/appsettings.js`:

- **Live search** — `#mail-search` filters as you type (250ms debounced `input` handler); Enter still fires
  immediately. Placeholder dropped the "(enter)" hint.
- **Removed the `threads` button**; conversation grouping moved into **mail settings** (a `mail_threads`
  choice: flat list / group by conversation). `_threads` is read from that setting at init and on
  `window._reloadMail` (which the settings `apply` calls).
- **Compose** moved to the **rightmost** action (refresh · rules · accounts · **compose**), the cog trails it.
  (rules/accounts stay in the bar for now — they move into settings in ui-4e.)

Tests: `tests/test_mail_ui.py::ToolbarCleanup4a` (6) + `docs/evidence/ui-4a/verify.py` (threads gone, live
search runs without Enter, compose rightmost, grouping in settings, 0 console errors) + `toolbar.png`.

# ui-4b — Gmail-style category sidebar

`static/index.html` + `static/js/mail.js` + `static/style.css`:

- The horizontal `#mail-tabs` strip is replaced by a **left sidebar** `#mail-sidebar` inside `.mail-layout`
  (`[sidebar] [list] [reading pane]`). `_MAIL_NAV` renders 9 icon+label rows
  (inbox·primary·social·promotions·unread·flagged·vip·sent·drafts) using the unified Stage-0 icon set
  (`window.icon`: mail/user/comment/tag/bell/bookmark/star/send/edit) — replacing the faint emoji.
- A `☰` toggle in the head collapses it to an **icons-only rail** (labels hidden); the collapsed state
  persists in `localStorage` (`mail-sidebar-collapsed`).
- `setFilter` now drives `.mail-nav-item.active`; clicking a row loads that category/folder as before.

Tests: `tests/test_mail_ui.py::Sidebar4b` (4) + `docs/evidence/ui-4b/verify.py` (9 icon rows, old tabs gone,
sidebar in the layout, default + click active state, collapse persists + hides labels, 0 console errors) +
`findings.md` (notes the populated-screenshot needs a connected account).

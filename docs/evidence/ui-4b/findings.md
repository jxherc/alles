# ui-4b — Gmail-style mail sidebar

Converted the horizontal `#mail-tabs` (inbox/primary/social/promotions/unread/flagged/vip/sent/drafts)
into a **left sidebar** (`#mail-sidebar` inside `.mail-layout`) of icon+label rows using the unified Stage-0
icon set (`window.icon`): mail / user / comment / tag / bell / bookmark / star / send / edit. A `☰` toggle in
the head collapses it to an icons-only rail; the collapsed state persists in localStorage.

Verified via `verify.py` (DOM-level, since the message panes only render with a connected account on this
isolated server): 9 rows, every row has an `svg` icon, old `.mail-tab` markup gone, sidebar lives in the
layout's left column, inbox active by default, clicking a category activates it, toggle collapses + persists
+ hides labels, 0 console errors. **Screenshot note:** the mail layout is hidden until a mail account is
connected (no IMAP creds in the throwaway test env), so a populated screenshot isn't capturable here; the
sidebar markup + styling are confirmed by the DOM assertions.

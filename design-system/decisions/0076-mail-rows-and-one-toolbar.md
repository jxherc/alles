# mail: two line rows, one toolbar, and states instead of banners

amends 0054 (mail's sidebar leaves, so it no longer resizes), 0055 (mail rows use the action menu),
and 0051 (mail rows sit the row gap apart; the 2px margin that beat it is gone).

## context

nov 10 design audit ("looks too AI"). a mail row was three lines (sender, subject, then five or six
icon buttons: unsubscribe, label, snooze, mute, archive, flag) about 132px tall, with no gap
between the buttons. a phone showed header, tabs, account, search, refresh and compose, a row of
folder chips and a red error strip before the first message, which started at y=497 of 844. with no
account the mail screen opened the accounts panel by itself, and the inbox overview drew three cards
of zeros.

## decision

- a message row is two lines: sender and time, then the subject. the row ends in the flag, a toggle
  that shows its state by its own mark (`aria-pressed`, a filled amber star) and no box, and one "..."
  button. the "..." opens the shared action menu (0055) with archive, snooze, label, mute and
  unsubscribe, which shows only for mail that has the header. every row is 76px (a 24px sender line, the 44px
  subject button and 4px of padding) so a list reads as a column, rows sit `--k-row-gap` apart, and the flag and "..."
  sit `--k-control-gap` apart, both 44px targets. unread shows by weight.
- the menu opens from the keyboard with arrow down and turns upward where the list ends. focus goes
  back to the row's "..." button after an action. the actions keep their data attributes and handlers.
  the list carries no snippet, so the second line is the subject only.
- with several accounts the account name is part of the time ("Work · Nov 10"), not a boxed badge on
  a third line.
- the folders are one dropdown in the toolbar (4 or more options, a list that can grow), so the folder
  sidebar and its collapse button are gone at every size. the toolbar is one row: account, folder,
  search, compose and a "..." button that holds refresh and mail settings (the gear is gone from mail,
  and pull to refresh is not built: refresh is a menu item). under 761px the toolbar is two rows:
  account, folder and "..." then search and compose, so the first message starts at y=228 on a 390px
  phone.
- a failed sync with saved mail on screen is a state: "offline, showing saved mail" and a retry button
  in the toolbar next to the folder, with the reasons in its title. it is one element, so a failed
  retry keeps focus, and it goes away by itself when a sync works. on a phone it is a short "offline"
  button in the first toolbar row, so it takes no row of its own. with nothing to show, the reason is
  the list, as an alert with retry.
- no mail account: one line "no mail account" and one button "add account", on the mail screen and in
  the inbox overview. the accounts panel (sign in buttons, app password form) opens only from that
  button or from "mail settings". compose hides until there is an account.

## where

`static/js/mail.js` (row markup, `_initMailToolbar`, `paintOffline`, `paintNoAccount`),
`static/js/specialist_groups.js` (overview), `static/index.html` (toolbar), `static/style.css`
(toolbar), `static/revamp.css` (rows), `static/kokuen.css` (`.mail-flag` keeps its own mark).

## checked

webkit at ipad landscape, ipad portrait and phone, chromium at 1440, dark and light, on throwaway data
with 20 messages (long subjects, long sender names, unread, flagged, one with an unsubscribe header)
in one and two accounts: every row 76px, rows 4px apart, flag and "..." 8px apart and 44px, first
message at y=132 (ipad landscape, desktop), y=184 (ipad portrait, offline), y=228 (phone). each menu
action ran and its result was read back (mute and snooze from the api, flag from the toggle, label
chip, archive against a mocked server).

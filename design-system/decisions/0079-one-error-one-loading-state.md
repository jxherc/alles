# one error state and one loading state

## context

a failed load showed two surfaces with two retry buttons: the shell's corner chip ("couldn't load
plan") and the pane's own message. the pane messages were drawn four ways (calendar a plain red line,
books a 13px line with a boxed retry, gallery plain text, journal a lock card that said "could not
verify the journal lock" for a network failure). while loading, calendar, its sidebar, gallery,
contacts and journal were blank, books and habits showed "loading ..." at another spot, and the
shell's "loading plan..." wrapped to two lines in an 80px corner.

## decision

- one component in `util.js`: `stateHtml` and `stateEl`. a failure is the shell's card (message,
  one 44px retry button) laid at the top of the pane it is about. a load in progress is a small box
  with the busy edge (decision 0053) and one line, "loading <app>...". a screen draws these and
  nothing of its own.
- the message names what failed and the retry reloads that pane. a pane that drew its own failure
  hides the shell's chip (`_paintSpecialistState`), so one failure shows one message and one retry.
  the chip stays for screens that draw nothing of their own.
- while a pane shows its loading box the shell's corner words step aside; the chip's words never
  wrap.
- journal says "couldn't load journal" with retry when it cannot reach the server. the lock card is
  only for a real lock. the two `journal.unavailable_*` texts are gone.
- used by calendar (list and sidebar), books, read, health, habits, gallery, photos, contacts and
  journal. old class names that gates read (`legacy-load-note`, `habit-load-error`) stay as extra
  classes.

## checked

webkit at ipad landscape and phone, dark and light: each of the nine screens with a failing and a
slow request shows one card and one retry (44px) or one loading box, retry loads the screen again, no
second surface, nothing off the edge.

## the model picker is a list on its button

the picker opened as a modal at the top left of the page while its button sat at the bottom right,
and carried a "newest only" switch, a refresh button and an endpoints tab next to the list.

- it is a popover on the button that opened it (`#model-modal`, no backdrop): above the button
  when the button is in the lower half of the window, below it otherwise, on the side the button is
  on, 21rem wide like the other composer menus, the shared menu look (0055). the same button shuts
  it. Escape closes it and focus goes back to the button.
- it holds a search field and the list of models, nothing else. with no models it says so and has
  one "settings" button.
- "show only the newest model of each family" and refresh live in settings > models (a labeled
  switch at the top of model connections; "refresh all" was already there). endpoints are added,
  tested and removed in settings only.

## the permission menu

it keeps one short line under each mode (they prevent a real mistake) and is 21rem wide like the
effort menu. the full access line is "no approval; the shell is unrestricted" so it fits on one
line at that width in every language.

## composer and header buttons keep a gap

jobs, call and more in the aide header, and model, mic and send in the composer, were separate
buttons laid out with a gap of 0 by `aidecentral.css` (the winning rule); the composer's own tools
sat 4px apart. every group now uses `--k-control-gap`. on a 360px phone the model name gives way
(ellipsis) so the send button stays on the row.

## the background work drawer

an empty drawer is one line, "no background work yet". the "scheduled work" action only appears
under real work; scheduled work is always in the more menu.

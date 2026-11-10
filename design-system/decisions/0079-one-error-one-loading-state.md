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

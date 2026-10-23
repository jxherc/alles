# one header row for every app

## context

A review of every screen found four header styles. Aide put its views ("conversation", "code")
in its 52px row; the nine specialist apps put theirs on a second row under a ruled header with a
"views" button at the far end; Home's header sat inside its content column with a clock ticking
seconds. The "views" button (decision 0007) collapsed the tab row in all nine apps at once and
remembered it, so one click made every app look like its views had vanished. Aide's tool pages
(brain, skills, models...) kept "conversation" marked as current.

## decision

- On wide screens every app's header is one 52px row: the app name (the switcher), then its
  views, then header actions such as Finance's guide at the far end. No rule under it, like
  Aide's. A phone keeps the 44px view row under the name (decision 0003).
- The "views" toggle and its stored collapse are gone; the view row is always there. This
  replaces that part of decision 0007.
- An old screen's own header that holds only its hidden title no longer leaves a blank row.
- Aide's tool pages mark neither "conversation" nor "code" as current.
- Home's header spans the window like the others, and its clock shows minutes, not seconds.

## verification

`tests/pw_phase8_specialist_real.py` checks the views sit in the name row on wide screens and on
their own row on a phone; the shell, Aide and Home browser gates pass.

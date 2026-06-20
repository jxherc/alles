# ui-7c — journal lock-now (findings)

## Audit
Reproduced live: the backend lock works (after "lock now" the data endpoint 403s and the lock screen
shows). The real defect was placement — the lock/change/disable picker rendered into `#jrnl-reflection`,
which lives in the main entry column (top:0), nowhere near the lock button at the top-right of the
toolbar. It looked like the button did nothing. The lock button + screen also used 🔒/🔓 emoji.

## Fix
Rebuilt the picker as a fixed, anchored dropdown under the lock button (dismiss on outside click) and
swapped the emoji for the central lock/unlock icons.

## Verify
`verify.py` sets a passcode, holds a token, then drives the real click: the menu appears as a fixed
dropdown within ~30px under the button (not in the reflection panel), and picking "lock now" shows the
lock screen, clears the token, and gates `/api/journal/<day>` to 403. 0 console errors.

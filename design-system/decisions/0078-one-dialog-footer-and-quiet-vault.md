# one dialog footer, a quiet vault, picking on demand

amends 0031 (buttons), 0055 (action menus) and 0064 (the app sheet).

## context

the nov 10 design audit found the same few causes on four screens.

- the vault toolbar had eight controls and wrapped to three rows on a phone. every entry row showed copy and a red delete at rest and the word "login" on every row. the entry dialog had an x and a cancel, and its footer wrapped to two rows.
- the gallery drew a white ring on every photo at rest, on the same 44px box as the photo's open button.
- the app sheet was 957px tall on an 844px phone, so search, help and settings were below the fold, and it did not show which app was open.
- docs, files and the vault each drew their dialog footer their own way: three footer looks, three gaps.

## decision

- a toolbar holds the controls used all the time and one more menu holds the rest. the vault toolbar is the vault dropdown (only with more than one vault), + new, lock and more (+ vault, travel, biometric, watchtower, settings).
- a row shows its name and quiet meta, and the type only when it is not the common one. a row ends with its main action (copy) and the shared row menu. delete lives in that menu, never as a red button at rest.
- a dialog has one way out: cancel in the footer, and escape. no x next to it. secondary actions of an existing item (share, revoke link, delete) sit in a more menu at the footer's start, so the footer reads more, cancel, save on one line.
- one footer rule draws every dialog footer: a quiet cancel, then the action as the one filled button, 44px, a control gap apart, on the right. the shared dialog, the vault's dialogs, docs' dialog and the files add-location, transfer and settings dialogs all use it.
- a password field takes a full row on a phone, its show, copy and gen under it.
- picking in the gallery is on demand: a select button (done while on), a long press, escape or the bar's x to end. while it is off there is no ring. while it is on a tap picks, and the photo's own button carries the picked state, so no two controls share a box. photos sit 4px apart.
- the app sheet is two columns of 44px rows, scrolls only when the screen is too short, keeps search, help and settings at its end, and marks the open app with aria-current="page" and weight.

## not done here

- files location settings still shows its helper sentence and two state lines, and money imports still draws its account and format as two boxes with a change button each. both are next.
- the vault's manage dialog keeps its x beside "done".

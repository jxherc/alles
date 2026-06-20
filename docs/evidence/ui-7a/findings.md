# ui-7a — contacts layout + de-icon (findings)

## Audit
Contacts is account-gated: on the test server the base view sits behind the account overlay (only
modals paint above it), so it can't be screenshotted — verified via the DOM instead (the established
pattern for gated apps). The top bar mixed emoji-labelled buttons (★ favorites, 🎂 birthdays) with
text ones (groups/duplicates/CardDAV/export/import); list rows put name + meta on one ellipsised line.

## Fix
- De-iconed the top bar: ★ → "favorites", 🎂 → "birthdays"; scoped `.contacts-head` with a growing
  search and export pushed right.
- Rebuilt list rows (`.contact-item`): star (icon) · avatar · stacked name/meta (`.contact-rowmain`) ·
  hover-revealed actions (`.contact-rowacts`), all aligned via flex.
- Unified the per-row star (★/☆ → star/star-fill icons), birthday cake, detail map-pin, "this is me"
  check, and every "← contacts" back button to the central icon set.

## Verify
`verify.py` (DOM on `contacts.localhost:8872`, seeds 2 contacts): fav/birthday buttons are text labels,
rows carry the rebuilt main/actions layout with an svg-icon star, no emoji in the list, detail opens
with an icon back button. 0 console errors.

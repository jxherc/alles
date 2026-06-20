# ui-7a — contacts layout fix + de-icon top buttons

The contacts top bar mixed emoji-labelled buttons (★ favorites, 🎂 birthdays) with text ones, and list
rows crammed name + meta onto one ellipsised line. Rebuilt both and unified every glyph to the Stage-0
icon set.

- **Top bar** (`static/index.html`): `.contacts-head`; ★ → "favorites", 🎂 → "birthdays"; search grows,
  export pushed right.
- **List rows** (`static/js/contacts.js`): `.contact-item` flex row — icon star · avatar ·
  `.contact-rowmain` (name over meta, stacked) · `.contact-rowacts` (open/del, hover-revealed).
- **Glyphs → icons**: per-row star ★/☆ → `star`/`star-fill`, birthday `cake`, detail map `map-pin`,
  "this is me" `check`, every "← contacts" back → `chevron-left` (via a `_si()` `window.icon` guard).
  (CardDAV pane glyphs are left to ui-7b, which re-homes it.)

Contacts is account-gated, so verification is DOM-level.

Tests: `tests/test_contacts_ui.py` (6 source-contract) + `docs/evidence/ui-7a/verify.py` (header text
labels, rebuilt row layout, icon star, no emoji in list, detail back is an icon, 0 console errors).

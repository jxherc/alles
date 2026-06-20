# ui-8e — customizable types (findings)

## Audit
The form's types were a hardcoded `TYPES` array keyed into `FIELD_DEFS`; the backend's category-schema
feature wasn't wired into it and only allowed picking known field keys — no way to define a new type or
custom fields with widths.

## Fix
Added a `vault_custom_types` setting + CRUD endpoints (with width/kind validation), refactored the form to
resolve fields through def objects so custom fields render (label/width/kind/placeholder), made the type
picker list built-in + custom types, and built a visual type editor in settings (type name + per-field
rows with width/kind segmented controls, add/remove fields).

## Bug caught in verify
The first run hit 405/404 — the running test server predated the new routes (Python doesn't hot-reload).
Restarted with the current code; the verify then passed. (Lesson: restart the server after backend edits.)

## Verify
`verify.py` builds a "Wi-Fi" type (network @ half width, passphrase @ secret), confirms it's listed and
persisted, then opens the add-secret form, selects the custom type, and sees the custom fields render.
0 console errors.

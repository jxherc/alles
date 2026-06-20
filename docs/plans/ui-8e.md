# ui-8e — customizable entry types (visual editor)

Users can now define their own vault item types — name them, add fields, set each field's width/kind —
and use them when adding a secret.

## Backend (`routes/vault.py`)
- A `vault_custom_types` setting: `{key: {label, fields:[{key,label,width,kind,placeholder}]}}`.
- `GET /vault/custom-types`, `PUT /vault/custom-types/{key}` (validates key+label, normalises width to
  full/half/third and kind to text/secret/password/textarea, requires ≥1 field), `DELETE …/{key}`.
- Entries already encrypt an arbitrary `fields` dict, so a custom-type entry round-trips with no change.

## Frontend (`static/js/vault.js`)
- Custom types are loaded on unlock (`_customTypes`). The add/edit form was refactored to resolve fields
  through **def objects** (`_defOf`/`_currentFields` now return `{key,label,kind,placeholder,half}`), so
  custom fields render with their own labels, widths (half-width pairs share a row) and placeholders. The
  type picker lists built-in + custom types (`_allTypes`).
- A **visual type editor** in the vault settings: list/add/edit/delete custom types; the editor has a type
  name, per-field rows (name input + width `.seg` + kind `.seg` + remove), an "+ field" button, and save —
  using the theme's segmented control (no native widgets).

Tests: `tests/test_vault_custom_types.py` (8: CRUD + width/kind validation + entry round-trip) +
`tests/test_vault_types_ui.py` (7 frontend contract) + `docs/evidence/ui-8e/verify.py` (live: build a
"Wi-Fi" type with a half-width + a secret field, then add a secret of that type and see the custom fields).

# Phase 6 — contacts (`contacts.js` + `routes/contacts.py` + `services/vcard.py`)

## Audit (2026-06-18)

Verified working (DO NOT rebuild): contact CRUD (name/email/phone/notes/tags), name search (`?q=`),
vCard import + export (backend `to_vcard`/`parse_vcards`, FN/N/EMAIL/TEL/NOTE). The UI (68 lines) is a
bare list+form and surfaces none of the vCard import/export, search, or tags.

Confirmed gaps: the model is minimal (no **company/title/address/birthday/website**); no **favorites**;
search is name-only (not email/phone/company); **upcoming birthdays** aren't surfaced; the vCard
import/export endpoints have no UI.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **contacts-1 Richer fields + vCard mapping.** Add company/title/address/birthday/website columns
  (migrations) through `_fmt`/create/patch; map them to vCard ORG/TITLE/ADR/BDAY/URL both ways. Edit form
  grows the fields. *Why: a contact without company/birthday/address isn't really a contact card.*
- **contacts-2 Favorites + full search.** Add a `favorite` column + `?favorites=` filter; widen `?q=`
  search to name/email/phone/company. UI: star toggle, search box, favorites filter. *Why: starring +
  finding by any field are table-stakes.*
- **contacts-3 Upcoming birthdays + vCard import/export UI.** GET `/api/contacts/birthdays?days=` (next N
  days, year-agnostic) + a birthdays view; surface import (file) / export (download) buttons. *Why:
  birthday reminders are a top Contacts feature, and the vCard backend was invisible.*

## Out of scope

Multiple emails/phones per contact (large model change for a single-user app), contact photos/avatars,
CardDAV server, duplicate-merge UI.

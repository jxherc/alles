# 8c — contacts depth — findings

Audited contacts by running an isolated server (`ALLES_DATA=/tmp/alles8c PORT=8866`) with curl + Playwright.

## Audit — state before the build
- `Contact` was flat: single email/phone/address + company/title/birthday/website/tags/favorite. No labeled
  multi-fields, no avatar, no groups, no duplicate-merge, no Me card. vCard import/export already existed.

## Built (gaps only)
- **8c-1 fields + avatar + Me** (`core/database.py`, `routes/contacts.py`): `ContactField` (kind/label/value
  with kinds email|phone|address|url|social|custom); `Contact.avatar` + `Contact.is_me`. Endpoints:
  `GET/POST/DELETE /contacts/{cid}/fields`, `POST/GET/DELETE /contacts/{cid}/avatar`, `GET /contacts/me`;
  `_fmt` carries fields/avatar/is_me; setting `is_me` is singular (clears it elsewhere).
- **8c-2 groups + dup-merge** (`core/database.py`, `routes/contacts.py`): `ContactGroup` (manual or smart by
  `rule_tag`/`rule_company`) + `ContactGroupMember`; group CRUD + computed members; `GET /contacts/duplicates`
  (union-find over normalized name + shared email); `POST /contacts/merge` (folds other's empty-fill scalars,
  unions tags, appends notes, moves labeled fields + memberships, deletes other).
- **8c-3 frontend** (`static/js/contacts.js`, `index.html`, `style.css`): list rows show avatar + Me badge;
  a contact detail panel (avatar upload, scalar fields, labeled-field add/remove with a custom-dropdown kind
  picker, set-as-me, address → OpenStreetMap map link); a groups panel (create incl. smart-by-tag) and a
  duplicates panel with a merge button. Stamps → v66 / SW v40.

## Exercised with real input
- Fields/avatar/Me: add field (6 kinds), list in fmt, delete, set/get avatar, avatar 404, singular Me,
  /contacts/me, custom label (unit `test_contacts_depth`, 11/11).
- Groups/merge: create, manual add, smart-by-tag, smart-by-company, delete, duplicates by name + by email,
  none-empty, merge combines fields + tags + moved labeled field, merge deletes other, unknown 404 (unit
  `test_contacts_groups`, 11/11).
- UI (Playwright `pw_contacts_8c`, 8/8): field add, avatar upload, Me badge, address map link, group create,
  smart membership computed, duplicate merge. Screenshots `contacts-list.png`, `groups.png`.

## Bugs / imperfections found
- **App bugs: none.** Notable test-infra learnings (not app bugs):
  - The service-worker write-queue intercepts JSON POSTs and can transiently return `{queued:true}` on first
    load → seed via Python `urllib` (IPv4, bypasses browser + SW) instead of page `fetch`.
  - A transient `net::ERR_CONNECTION_CLOSED` (Windows uvicorn dropping a keep-alive under rapid requests) can
    make a `loadX` show "failed to load"; the test reloads once if the list doesn't appear. Recoverable, and
    the app already shows a clean "failed to load" state — not worth an app change.
- Filename collision avoided: existing `tests/test_contacts_fields.py` is the vCard suite; the new backend
  tests live in `tests/test_contacts_depth.py`.

## Evidence
`pw_contacts_8c.txt` (8/8), `contacts-list.png`, `groups.png`. Unit: 22 tests across two files.

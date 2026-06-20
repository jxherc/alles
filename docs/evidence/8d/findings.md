# 8d — CardDAV sync — findings

Audited against the existing `services/caldav_sync.py` template + ran an isolated server
(`ALLES_DATA=/tmp/alles8d PORT=8867`) with Playwright.

## Audit — state before the build
- `caldav_sync.py` was the only DAV sync (calendar). No CardDAV equivalent. `services/vcard.py` has
  `parse_vcards`/`to_vcard`. `Contact` had no sync columns.

## Built (gaps only)
- **8d-1 carddav_sync** (`core/database.py`, `services/carddav_sync.py`, `routes/carddav.py`, `app.py`):
  `Contact.carddav_uid/href/etag`; a testable sync core with an **injectable client** —
  `parse_report(xml)` (CardDAV multistatus → href/etag/vcard), `vcard_uid(text)`, `build_vcard(contact,uid)`,
  `sync(client, db)` that pulls remote (match by UID, update/create) and pushes local-only (PUT → stamp uid).
  A real `_RealClient` does raw CardDAV over httpx (REPORT + PUT) when no client is injected.
  `status/connect/disconnect/sync` endpoints under `/api/carddav`; config in `<data>/carddav.json`
  (now respects `ALLES_DATA`, unlike the older caldav one).
- **8d-2 frontend** (`static/js/contacts.js`, `index.html`, `style.css`): a CardDAV button → a panel showing
  connection status, a connect dialog (url/username/password), a sync action that reports pulled/pushed (or a
  graceful error), and disconnect. Stamps → v67 / SW v41.

## Exercised
- Unit (`test_carddav`, 10/10): parse_report extracts 2 entries; vcard_uid; build_vcard has FN+UID;
  pull creates; pull updates (no dupes); push local-only (client.put called); push stamps uid+href;
  idempotent; not-configured → error; status shape. Sync runs with an injected `FakeClient` (no network).
- UI (Playwright `pw_carddav_8d`, 8/8): button, connect dialog with 3 fields, connect saves + shows
  "connected as alice", sync runs against a bogus server and surfaces a graceful error result, disconnect
  clears status. Zero console errors. Screenshot `carddav.png`.

## Bugs / imperfections found
- **App bugs: none.** The real network client isn't unit-tested (needs a live CardDAV server, same as
  caldav) — it's covered structurally and exercised end-to-end via the UI against a refused connection.
- Improved isolation over caldav: CardDAV config path uses `data_dir()` so test/isolated instances don't
  write into the repo's `data/`.

## Evidence
`pw_carddav_8d.txt` (8/8), `carddav.png`. Unit: 10 tests.

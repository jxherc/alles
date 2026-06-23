# stage 3h - multi-format export framework - audit findings (2026-06-23)

## current state
- export is one-off + scattered: contacts -> vCard (services/vcard.to_vcard), calendar -> iCal
  (services/ics.to_ics). each is its own endpoint. there is NO generic export: tasks/notes/transactions
  can't be exported at all, and there's no JSON/CSV/OPML anywhere.
- `ApiToken` exists but carries NO scopes; OpenAPI is already auto-served by FastAPI (/openapi.json).

## scope (this stage)
the broad 3h bullet bundles four subsystems. delivering the concrete, testable, genuinely-missing core:
a **unified multi-format export framework**. explicitly DEFERRED (noted, not silently dropped):
- TS SDK codegen = external build tooling; OpenAPI is already served, so the input exists.
- inbound connector framework with conflict resolution = its own large subsystem (own stage later).
- token scopes = a small follow-on; the export endpoints are read-only over already-authed app data.

## the gap
- pure encoders for the formats we lack: JSON, CSV, OPML.
- one registry mapping (kind -> {format -> builder}) reusing the existing iCal/vCard encoders, so
  tasks/notes/transactions/contacts/calendar all export through one path + endpoint.

## fix - new `services/exporters.py`
- `to_json(rows)`, `to_csv(rows)` (union-of-keys header, RFC-4180 quoting), `to_opml(items)`.
- `export(db, kind, fmt)` -> (content, media_type, filename); EXPORTERS registry per kind lists its
  allowed formats + a row builder; contacts->vcard + calendar->ics reuse the existing encoders.
- route GET /api/export/{kind}?format=... + GET /api/export (list kinds+formats).

tested: csv header/quoting/empty, json round-trip, opml structure, export tasks csv+json over a seeded
db, notes csv, transactions csv, unknown kind + unknown format errors, kinds listing.

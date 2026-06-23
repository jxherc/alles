# stage 0b - soft-delete / archive polymorphism - audit findings (2026-06-23)

audited every soft-delete / archive / trash flow by exercising the real routes + verifying DB
state (`.tmp_audit_0b.py`, in-process TestClient over a temp sqlite).

## the two mechanisms (the inconsistency)
| model | column | semantics |
|---|---|---|
| Session | `archived` (bool) | user-hidden, reversible, never purged |
| Note | `archived` (bool) | same |
| Account (money) | `archived` (bool) | same |
| Habit | `archived` (bool) | same |
| ReadItem | `archived` (bool) | same |
| Photo | `deleted_at` (datetime) | trashed, TTL-purged (30d) via TrashItem + services/trash.py |

so "give me the live rows" is `Model.archived == False` for 5 models but `Photo.deleted_at == None`
for the 6th - and that filter is hand-written ~20+ times across routes (grep: routes/notes.py:70,
92; sessions.py:57,377; search.py:90,101; money.py:975-1418; photos.py:197,364,381; shared.py).
`TrashItem` (services/trash.py) only registers kind file|photo.

## flows exercised (all WORK - both axes pass)
- **note archive**: `POST /api/notes/{id}/archive {archived:true}` -> live list 1->0,
  `?archived=true` list = 1, db.archived = True. correct.
- **note unarchive / default filter**: `GET /api/notes` filters `archived == False` by default. correct.
- **session archive**: `POST /api/sessions/{id}/archive` -> db.archived = True; GET /api/sessions
  (a grouped dict today/yesterday/earlier) excludes it. correct. (initial "3->3" was a len()
  misread of the dict response, not a bug.)
- **photo soft-delete + restore**: set `deleted_at` -> `POST /api/photos/{id}/restore` clears it,
  db.deleted_at = None. correct.
- **read create**: 200. fine.

## conclusion
nothing is broken - all lifecycle flows function + read correctly. the issue is purely
**duplication + lack of a uniform contract**: two mechanisms, the live/inactive filter copied
~20x, and no single place that says "how does model X soft-delete". later foundations (the
mutation spine's audit, the blob GC, connectors) want to assume one lifecycle contract.

## fix (lean - do NOT rewrite working routes wholesale)
add `services/lifecycle.py`: a `LIFECYCLE` registry (model -> archived|deleted_at) + helpers
`is_active(obj)`, `active(query)`, `inactive(query)`, `soft_delete(db,obj)`, `restore(db,obj)`
that dispatch to the right mechanism. adopt in the 2-3 cleanest high-dup spots (notes list +
tags, sessions list) to validate + remove real dup; leave the rest (they work) for incremental
adoption by later stages. cascade (trash children) is a documented extension point, not built
speculatively (no adopted model needs it yet).

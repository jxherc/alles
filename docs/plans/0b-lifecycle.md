# stage 0b - soft-delete / archive polymorphism

Audit (docs/evidence/0b-lifecycle): all lifecycle flows work; the issue is duplication - 2
mechanisms (`archived` flag x5 models, `deleted_at` x1) and the live-rows filter hand-written
~20x. Build a lean uniform contract; adopt where it cleanly removes dup; don't rewrite working
routes.

## design - services/lifecycle.py
- `LIFECYCLE` registry: `{Model: (column, kind)}` where kind is "flag" (archived bool) or
  "ts" (deleted_at datetime). Covers Session, Note, Account, Habit, ReadItem, Photo.
- `is_active(obj) -> bool` - dispatch on the model's policy.
- `active(query)` / `inactive(query)` - add the right filter (introspect model via
  `query.column_descriptions[0]["entity"]`).
- `soft_delete(db, obj)` / `restore(db, obj)` - set/clear the right column, commit.
- cascade = documented extension point, NOT built (no adopted model needs it).

## tasks

### Task 0b-1 - the lifecycle helper  (tests: tests/test_lifecycle.py)
RED tests (>=8): registry covers all 6 models; is_active True for a live Note + False when
archived; is_active True for a live Photo + False when deleted_at set; active(query) excludes
archived Notes; active(query) excludes deleted Photos; inactive(query) returns only archived
Notes; inactive returns only deleted Photos; soft_delete sets archived on a Note (is_active
False after); soft_delete sets deleted_at on a Photo; restore clears archived; restore clears
deleted_at.

### Task 0b-2 - adopt in notes + sessions (remove real dup)  (tests: integration)
Adopt `active`/`inactive` in `routes/notes.py` list_notes (archived param) + list_tags, and
`routes/sessions.py` list (archived==False). RED/regression tests: GET /api/notes default hides
archived + ?archived=true shows only archived (unchanged behavior via the helper); GET
/api/sessions excludes an archived session; list_tags ignores archived notes' tags.

## verification
- `python -m unittest tests.test_lifecycle` green.
- existing note/session/photo route tests still green (behavior identical).
- full suite green.

# stage 0a - migration framework - audit findings (2026-06-23)

audited the current schema-init subsystem by running it against isolated DBs
(`ALLES_DATA=.tmp_0a_audit`). evidence: `baseline-schema.json` (full table/column dump).

## what was exercised
- **fresh boot**: `init_db()` on an empty DB -> `Base.metadata.create_all` + 81 `_add_col`
  ALTERs + `_encrypt_plaintext_secrets`. result: **76 tables, 616 columns**. clean, no error.
- **idempotency**: ran `init_db()` twice on the same DB -> identical schema, no error
  (every `_add_col` re-throws "duplicate column" internally and swallows it).
- **partial-DB repair**: `ALTER TABLE notes DROP COLUMN due` then `init_db()` -> `notes.due`
  re-added. so the current mechanism self-heals a missing migrated column.
- **error path**: `_add_col(conn, "tasks", "bogus col with spaces!!", "NOTATYPE")` (a genuinely
  invalid ALTER) -> **silently swallowed**, no error raised, no column added.
- **full app import**: `import app` on the isolated DB -> OK.
- sqlite version 3.43.1 (supports `ALTER TABLE ... DROP COLUMN`, used in tests).

## how it works today (`core/database.py`)
- `init_db()` (lines 1133-1243): `create_all(engine)` then ~81 `_add_col(conn,table,col,type)`
  calls (one `for` loop over 6 contact columns) then `_encrypt_plaintext_secrets()`.
- `_add_col(conn,table,col,type)` (1125-1130): `ALTER TABLE ... ADD COLUMN` wrapped in a
  bare `try/except: pass`.

## problems found (motivate the new framework - both axes: works + maintainable)
1. **silent failure (works-wrong risk)**: `_add_col` swallows EVERY exception, so a genuinely
   broken migration (bad type, typo'd table, constraint violation) is invisible - the DB is
   silently left wrong. Confirmed live.
2. **no version record**: nothing tracks which migrations have run. Every boot re-attempts all
   81 ALTERs (each throws+swallows on an existing DB). No history, no "what changed when", no
   way to test a single migration or roll one back.
3. **unreviewable growth**: new schema changes append to a 110-line function; a reviewer can't
   see "this PR adds migration N" in isolation.
4. NOT broken: idempotency + self-heal + fresh-boot all work and MUST be preserved exactly.

## fix (stage plan)
A declarative runner + a `schema_migrations` version table; the 81 `_add_col` calls squash into
a single idempotent `m0001_baseline`; a new `add_column` helper that is idempotent (checks
`PRAGMA table_info` first) BUT surfaces real errors instead of swallowing them. `init_db` keeps
`create_all` (greenfield) then calls the runner. Behavior preserved: fresh boot, idempotency,
self-heal all unchanged; gained: version tracking, isolated/testable/reversible migrations,
real error surfacing for future migrations.

# stage 0a - declarative migration framework

Replace the 81 silent `_add_col` calls in `core/database.init_db` with a versioned migration
runner. Preserve fresh-boot / idempotency / self-heal exactly (audit: docs/evidence/0a-migrations).
Gain: a `schema_migrations` version record, isolated/testable/reversible migrations, and real
error surfacing (the old `_add_col` swallowed everything).

## design
- `core/migrations/` package. `runner.py`:
  - `run_migrations(engine, *, modules=None) -> list[int]` - ensure `schema_migrations`
    (version PK, name, applied_at), read applied, apply each pending module's `up(conn)` in a
    transaction, record the version. Surfaces errors from `up` (no swallow).
  - `applied_versions(conn) -> set[int]`, `discover(pkg) -> [module]` (sorted by VERSION).
  - `add_column(conn, table, col, coltype) -> bool` - idempotent via `PRAGMA table_info`
    (skip if present) but RAISES on a real error (bad table/type). The improvement over `_add_col`.
- migration modules `m0001_baseline.py` ...: `VERSION:int`, `NAME:str`, `up(conn)`, opt `down(conn)`.
- `m0001_baseline.up` = the exact 81 `_add_col` calls, rewritten as `add_column(...)` (idempotent
  + error-surfacing). A no-op on already-migrated/fresh DBs.
- `core/database.init_db`: keep `create_all` then `run_migrations(engine)` then
  `_encrypt_plaintext_secrets`. Drop the inline `_add_col` block (keep `_add_col` def for
  back-compat callers if any; grep shows only init_db uses it -> can remove after).

## tasks

### Task 0a-1 - runner + add_column helper  (tests: tests/test_migrations.py)
RED tests (>=8): ensure schema_migrations created; applied_versions empty then populated;
run_migrations applies a fake pending module + records (version,name,applied_at); skips an
already-applied version (up not re-run - assert via a call counter); applies multiple in
VERSION order; idempotent (second run applies []); a module whose up() raises propagates (not
swallowed) + version NOT recorded; down() reverts where defined; add_column adds a missing col;
add_column idempotent on an existing col (returns False, no error); add_column RAISES on a
nonexistent table (distinguishes from old silent _add_col).

### Task 0a-2 - baseline squash + init_db integration  (tests: tests/test_migrations.py cont.)
RED tests (>=8): m0001 has VERSION==1 + NAME=='baseline'; discover() finds it; m0001.up on a
create_all'd fresh DB is a no-op (no new cols) + records version 1; m0001.up on a stripped DB
(drop notes.due) re-adds it; full init_db on a fresh DB -> schema_migrations has row (1,baseline)
+ the same 76 tables / 616 columns as the audit baseline (regression vs baseline-schema.json);
init_db idempotent (second call applies no migrations, schema identical); init_db self-heal
(drop a col -> init_db re-adds via baseline re-run? note: baseline is recorded so it won't
re-run - self-heal now needs the runner to detect drift OR we accept create_all+baseline-once;
DECISION: keep a "repair" pass that re-runs baseline's add_column set when a tracked col is
missing, OR document that self-heal is via re-applying baseline when schema_migrations is reset.
Simplest faithful: init_db always runs the baseline add_column set idempotently REGARDLESS of
version record (cheap, preserves self-heal), and the version record governs only NEW numbered
migrations 0002+. -> test self-heal works); import app clean.

## verification
- `python -m unittest tests.test_migrations` green.
- fresh-DB `init_db` matches docs/evidence/0a-migrations/baseline-schema.json (76 tables/616 cols).
- `import app` clean; full suite green.

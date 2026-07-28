"""m0036 - generalized durable path claims for Files operations."""

from sqlalchemy import text

VERSION = 36
NAME = "file_operation_path_claims"


def _create_overlap_trigger(conn, action: str) -> None:
    # claim_scope is the canonical physical namespace (including the remote endpoint/bucket).
    # It intentionally crosses location_id aliases that point at the same storage; comparing
    # location_id here would let two aliases mutate the same path concurrently.
    existing_path = "rtrim(existing.normalized_path, '/')"
    new_path = "rtrim(NEW.normalized_path, '/')"
    exclude_current = "existing.id != OLD.id AND " if action == "UPDATE" else ""
    same_path = f"({existing_path} = {new_path})"
    new_descendant = f"(substr({new_path},1,length({existing_path})+1) = {existing_path} || '/')"
    existing_descendant = f"(substr({existing_path},1,length({new_path})+1) = {new_path} || '/')"
    overlap = (
        f"{exclude_current}existing.claim_scope = NEW.claim_scope "
        "AND existing.operation_id != NEW.operation_id "
        f"AND ({same_path} "
        f"OR {existing_path} = '' OR {new_path} = '' "
        f"OR {new_descendant} OR {existing_descendant})"
    )
    conn.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS "
            f"trg_file_operation_path_claim_overlap_{action.lower()} "
            f"BEFORE {action} ON file_operation_path_claims FOR EACH ROW "
            f"WHEN EXISTS (SELECT 1 FROM file_operation_path_claims existing WHERE {overlap}) "
            "BEGIN SELECT RAISE(ABORT, 'file operation path already in use'); END"
        )
    )


def _legacy_source_claims_exist(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='file_operation_source_claims'"
            )
        ).scalar()
    )


def _migrate_source_claims(conn) -> None:
    if not _legacy_source_claims_exist(conn):
        return
    conn.execute(
        text(
            "INSERT INTO file_operation_path_claims "
            "(id,operation_id,location_id,claim_scope,normalized_path,created_at) "
            "SELECT 'legacy-source:' || legacy.operation_id, legacy.operation_id, "
            "legacy.location_id, legacy.claim_scope, "
            "CASE WHEN legacy.claim_scope='local-physical' "
            "THEN lower(legacy.normalized_path) ELSE legacy.normalized_path END, "
            "legacy.created_at "
            "FROM file_operation_source_claims legacy "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM file_operation_path_claims current "
            "WHERE current.operation_id = legacy.operation_id "
            "AND current.claim_scope = legacy.claim_scope "
            "AND current.normalized_path = CASE WHEN legacy.claim_scope='local-physical' "
            "THEN lower(legacy.normalized_path) ELSE legacy.normalized_path END)"
        )
    )


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS file_operation_path_claims ("
            "id VARCHAR NOT NULL PRIMARY KEY, operation_id VARCHAR NOT NULL, "
            "location_id VARCHAR NOT NULL, claim_scope VARCHAR NOT NULL, "
            "normalized_path VARCHAR NOT NULL, created_at DATETIME, "
            "CONSTRAINT uq_file_operation_path_claim_operation_scope_path "
            "UNIQUE (operation_id,claim_scope,normalized_path), "
            "FOREIGN KEY(operation_id) REFERENCES file_operations(id) ON DELETE CASCADE, "
            "FOREIGN KEY(location_id) REFERENCES storage_locations(id) ON DELETE RESTRICT)"
        )
    )
    for name, column in {
        "ix_file_operation_path_claims_operation_id": "operation_id",
        "ix_file_operation_path_claims_location_id": "location_id",
        "ix_file_operation_path_claims_claim_scope": "claim_scope",
        "ix_file_operation_path_claims_normalized_path": "normalized_path",
    }.items():
        conn.execute(
            text(f'CREATE INDEX IF NOT EXISTS "{name}" ON file_operation_path_claims("{column}")')
        )
    # A database that already ran the original m0035 may legitimately contain
    # root and descendant claims created before root overlap was enforced. Copy
    # that durable recovery state before installing the stricter generalized
    # triggers so the upgrade itself cannot strand the application at startup.
    for action in ("insert", "update"):
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_file_operation_path_claim_overlap_{action}"))
    _migrate_source_claims(conn)
    _create_overlap_trigger(conn, "INSERT")
    _create_overlap_trigger(conn, "UPDATE")

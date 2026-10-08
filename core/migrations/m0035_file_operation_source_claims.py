"""m0035 - durable exclusive claims for restart-safe Files source mutations."""

from sqlalchemy import text

VERSION = 35
NAME = "file_operation_source_claims"


def _create_overlap_trigger(conn, action: str) -> None:
    existing_path = "rtrim(existing.normalized_path, '/')"
    new_path = "rtrim(NEW.normalized_path, '/')"
    same_path = f"({existing_path} = {new_path})"
    new_descendant = f"(substr({new_path},1,length({existing_path})+1) = {existing_path} || '/')"
    existing_descendant = f"(substr({existing_path},1,length({new_path})+1) = {new_path} || '/')"
    overlap = (
        "existing.claim_scope = NEW.claim_scope AND existing.operation_id != NEW.operation_id "
        f"AND ({same_path} OR {existing_path} = '' OR {new_path} = '' "
        f"OR {new_descendant} OR {existing_descendant})"
    )
    conn.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS "
            f"trg_file_operation_source_claim_overlap_{action.lower()} "
            f"BEFORE {action} ON file_operation_source_claims FOR EACH ROW "
            f"WHEN EXISTS (SELECT 1 FROM file_operation_source_claims existing WHERE {overlap}) "
            "BEGIN SELECT RAISE(ABORT, 'file operation source already in use'); END"
        )
    )


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS file_operation_source_claims ("
            "operation_id VARCHAR PRIMARY KEY, location_id VARCHAR NOT NULL, "
            "claim_scope VARCHAR NOT NULL, normalized_path VARCHAR NOT NULL, created_at DATETIME, "
            "CONSTRAINT uq_file_operation_source_claim_scope_path "
            "UNIQUE (claim_scope,normalized_path), "
            "FOREIGN KEY(operation_id) REFERENCES file_operations(id) ON DELETE CASCADE, "
            "FOREIGN KEY(location_id) REFERENCES storage_locations(id) ON DELETE RESTRICT)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_file_operation_source_claims_claim_scope "
            "ON file_operation_source_claims(claim_scope)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_file_operation_source_claims_location_id "
            "ON file_operation_source_claims(location_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_file_operation_source_claims_normalized_path "
            "ON file_operation_source_claims(normalized_path)"
        )
    )
    _create_overlap_trigger(conn, "INSERT")
    _create_overlap_trigger(conn, "UPDATE")

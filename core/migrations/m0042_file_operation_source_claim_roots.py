"""m0042 - make a storage-root source claim overlap every descendant."""

from sqlalchemy import text

from core.migrations import m0035_file_operation_source_claims

VERSION = 42
NAME = "file_operation_source_claim_roots"


def up(conn):
    for action in ("insert", "update"):
        conn.execute(
            text(f"DROP TRIGGER IF EXISTS trg_file_operation_source_claim_overlap_{action}")
        )
    m0035_file_operation_source_claims._create_overlap_trigger(conn, "INSERT")
    m0035_file_operation_source_claims._create_overlap_trigger(conn, "UPDATE")

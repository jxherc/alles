"""m0044 - canonicalize legacy local claims for Unicode-safe filesystem identity."""

from pathlib import Path

from sqlalchemy import text

from core.database import canonical_local_physical_claim_path, local_claim_case_insensitive
from core.migrations import (
    m0035_file_operation_source_claims,
    m0036_file_operation_path_claims,
)

VERSION = 44
NAME = "local_source_claim_casefold"


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"),
            {"table": table},
        ).scalar()
    )


def _claim_identity(scope: str, value: str) -> tuple[str, str]:
    if scope == "local-physical-ci":
        return scope, canonical_local_physical_claim_path(value)
    case_insensitive = local_claim_case_insensitive(Path(value))
    return (
        f"local-physical-{'ci' if case_insensitive else 'cs'}",
        canonical_local_physical_claim_path(value, case_sensitive=not case_insensitive),
    )


def _paths_overlap(left: str, right: str) -> bool:
    left = left.rstrip("/")
    right = right.rstrip("/")
    return (
        not left
        or not right
        or left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _assert_no_cross_operation_overlaps(conn, table: str, id_column: str) -> None:
    if not _table_exists(conn, table):
        return
    rows = [
        (claim_id, operation_id, *_claim_identity(scope, path))
        for claim_id, operation_id, scope, path in conn.execute(
            text(
                f"SELECT {id_column},operation_id,claim_scope,normalized_path FROM {table} "
                "WHERE claim_scope IN ('local-physical','local-physical-ci')"
            )
        ).all()
    ]
    for index, (_claim_id, operation_id, scope, path) in enumerate(rows):
        for _other_id, other_operation_id, other_scope, other_path in rows[index + 1 :]:
            if (
                operation_id != other_operation_id
                and scope == other_scope
                and _paths_overlap(path, other_path)
            ):
                raise RuntimeError(
                    f"{table} contains local claims that overlap after Unicode casefolding"
                )


def _canonicalize_table(conn, table: str, id_column: str) -> None:
    if not _table_exists(conn, table):
        return
    rows = conn.execute(
        text(
            f"SELECT {id_column},claim_scope,normalized_path FROM {table} "
            "WHERE claim_scope IN ('local-physical','local-physical-ci')"
        )
    ).all()
    for claim_id, scope, path in rows:
        target_scope, canonical = _claim_identity(scope, path)
        conn.execute(
            text(
                f"UPDATE {table} SET claim_scope=:scope, normalized_path=:path "
                f"WHERE {id_column}=:claim_id"
            ),
            {"scope": target_scope, "path": canonical, "claim_id": claim_id},
        )


def up(conn):
    trigger_sets = (
        ("source", "file_operation_source_claims"),
        ("path", "file_operation_path_claims"),
    )
    for _trigger_name, table in trigger_sets:
        id_column = "operation_id" if table == "file_operation_source_claims" else "id"
        _assert_no_cross_operation_overlaps(conn, table, id_column)
    for trigger_name, table in trigger_sets:
        if not _table_exists(conn, table):
            continue
        for action in ("insert", "update"):
            conn.execute(
                text(
                    f"DROP TRIGGER IF EXISTS trg_file_operation_{trigger_name}_claim_"
                    f"overlap_{action}"
                )
            )

    _canonicalize_table(conn, "file_operation_source_claims", "operation_id")
    _canonicalize_table(conn, "file_operation_path_claims", "id")

    if _table_exists(conn, "file_operation_source_claims"):
        m0035_file_operation_source_claims._create_overlap_trigger(conn, "INSERT")
        m0035_file_operation_source_claims._create_overlap_trigger(conn, "UPDATE")
    if _table_exists(conn, "file_operation_path_claims"):
        m0036_file_operation_path_claims._create_overlap_trigger(conn, "INSERT")
        m0036_file_operation_path_claims._create_overlap_trigger(conn, "UPDATE")

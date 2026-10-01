"""m0033 - stable Files location identity without deleting legacy path columns."""

import json
import os
from datetime import UTC, datetime

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 33
NAME = "storage_locations"

DEFAULT_LOCATION_ID = "default-local"


def _identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _tables(conn) -> set[str]:
    return {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _normalize(value: str, *, table: str, row_id: str, allow_root: bool = False) -> str:
    raw = str(value or "")
    if os.name == "nt":
        raw = raw.replace("\\", "/")
    raw = raw.strip("/")
    parts = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise RuntimeError(f"unsafe legacy Files path in {table} row {row_id}")
        parts.append(part)
    normalized = "/".join(parts)
    if not normalized:
        if allow_root:
            return ""
        raise RuntimeError(f"empty legacy Files path in {table} row {row_id}")
    return normalized


def _create_location_tables(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS storage_locations ("
            "id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, kind VARCHAR NOT NULL, "
            "access VARCHAR NOT NULL DEFAULT 'read_only', root_path TEXT DEFAULT '', "
            "endpoint TEXT DEFAULT '', bucket VARCHAR DEFAULT '', prefix TEXT DEFAULT '', "
            "config TEXT DEFAULT '{}', secret TEXT DEFAULT '', enabled BOOLEAN DEFAULT 1, "
            "is_default BOOLEAN DEFAULT 0, created_at DATETIME, updated_at DATETIME)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_storage_locations_kind ON storage_locations(kind)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_storage_locations_is_default "
            "ON storage_locations(is_default)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS file_operations ("
            "id VARCHAR PRIMARY KEY, action VARCHAR NOT NULL, source_location_id VARCHAR NOT NULL, "
            "source_path VARCHAR NOT NULL DEFAULT '', destination_location_id VARCHAR, "
            "destination_path VARCHAR DEFAULT '', state VARCHAR NOT NULL DEFAULT 'queued', "
            "bytes_total INTEGER DEFAULT 0, bytes_done INTEGER DEFAULT 0, error_code VARCHAR DEFAULT '', "
            "undo_json TEXT DEFAULT '{}', created_at DATETIME, updated_at DATETIME)"
        )
    )
    for name, columns in {
        "ix_file_operations_action": "action",
        "ix_file_operations_source_location_id": "source_location_id",
        "ix_file_operations_destination_location_id": "destination_location_id",
        "ix_file_operations_state": "state",
        "ix_file_operations_created_at": "created_at",
    }.items():
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON file_operations("{columns}")'))
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS storage_location_migration_audits ("
            "id VARCHAR PRIMARY KEY, location_id VARCHAR NOT NULL, counts_json TEXT NOT NULL, "
            "created_at DATETIME)"
        )
    )


def _needs_default_location(conn, tables: set[str]) -> bool:
    checks = (
        ("file_tags", ""),
        ("file_versions", ""),
        ("file_comments", ""),
        ("trash_items", "WHERE kind='file'"),
        ("shares", "WHERE kind IN ('file','folder')"),
        ("index_chunks", "WHERE kind='file'"),
    )
    for table, where in checks:
        if table not in tables:
            continue
        if conn.execute(text(f'SELECT 1 FROM "{table}" {where} LIMIT 1')).first():
            return True
    return False


def _ensure_default_location(conn) -> None:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    conn.execute(
        text(
            "INSERT OR IGNORE INTO storage_locations "
            "(id,name,kind,access,root_path,endpoint,bucket,prefix,config,secret,enabled,"
            "is_default,created_at,updated_at) VALUES "
            "(:id,'on this server','local','managed','','','','','{}','',1,1,:now,:now)"
        ),
        {"id": DEFAULT_LOCATION_ID, "now": now},
    )


def _has_path_only_unique(conn) -> bool:
    for row in conn.execute(text("PRAGMA index_list(file_tags)")):
        if not bool(row[2]):
            continue
        index_name = row[1]
        columns = [
            item[2] for item in conn.execute(text(f'PRAGMA index_info("{index_name}")')).fetchall()
        ]
        if columns == ["path"]:
            return True
    return False


def _create_file_tags(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE file_tags ("
            "id VARCHAR PRIMARY KEY, path VARCHAR, location_id VARCHAR NOT NULL, "
            "normalized_path VARCHAR NOT NULL, tags VARCHAR DEFAULT '', color VARCHAR DEFAULT '', "
            "starred BOOLEAN DEFAULT 0, created_at DATETIME, "
            "CONSTRAINT uq_file_tags_location_path UNIQUE (location_id, normalized_path), "
            "FOREIGN KEY(location_id) REFERENCES storage_locations(id) ON DELETE RESTRICT)"
        )
    )
    for name, column in {
        "ix_file_tags_path": "path",
        "ix_file_tags_location_id": "location_id",
        "ix_file_tags_normalized_path": "normalized_path",
    }.items():
        conn.execute(text(f'CREATE INDEX "{name}" ON file_tags("{column}")'))


def _merge_csv(first: str, second: str) -> str:
    values = []
    seen = set()
    for raw in (first, second):
        for value in str(raw or "").split(","):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return ",".join(values)


def _earliest(value, other):
    if value is None:
        return other
    if other is None:
        return value
    return value if str(value) <= str(other) else other


def _migrate_file_tags(conn, tables: set[str]) -> None:
    if "file_tags" not in tables:
        _create_file_tags(conn)
        return
    columns = _columns(conn, "file_tags")
    rows = conn.execute(text("SELECT * FROM file_tags ORDER BY id")).mappings().all()
    prepared_by_identity = {}
    had_duplicate_identity = False
    for row in rows:
        source_path = row.get("normalized_path") or row.get("path")
        root_candidate = str(source_path or "")
        if os.name == "nt":
            root_candidate = root_candidate.replace("\\", "/")
        root_candidate = root_candidate.strip("/")
        normalized = (
            ""
            if not root_candidate
            else _normalize(
                source_path,
                table="file_tags",
                row_id=str(row.get("id", "")),
            )
        )
        location_id = row.get("location_id") or DEFAULT_LOCATION_ID
        identity = (location_id, normalized)
        candidate = {
            "id": row.get("id"),
            "path": row.get("path") if row.get("path") is not None else normalized,
            "location_id": location_id,
            "normalized_path": normalized,
            "tags": row.get("tags") or "",
            "color": row.get("color") or "",
            "starred": bool(row.get("starred")),
            "created_at": row.get("created_at"),
        }
        existing = prepared_by_identity.get(identity)
        if existing is None:
            prepared_by_identity[identity] = candidate
            continue
        # Legacy path spellings such as /note.md and note.md can collapse to
        # one stable identity. Keep the first row id/path deterministically,
        # union its tags, retain the first available color, preserve any star,
        # and keep the earliest creation time.
        had_duplicate_identity = True
        existing["tags"] = _merge_csv(existing["tags"], candidate["tags"])
        existing["color"] = existing["color"] or candidate["color"]
        existing["starred"] = bool(existing["starred"] or candidate["starred"])
        existing["created_at"] = _earliest(existing["created_at"], candidate["created_at"])

    prepared = list(prepared_by_identity.values())

    needs_rebuild = (
        "location_id" not in columns
        or "normalized_path" not in columns
        or _has_path_only_unique(conn)
        or had_duplicate_identity
    )
    if needs_rebuild:
        conn.execute(text("ALTER TABLE file_tags RENAME TO file_tags_m0033_legacy"))
        # SQLite keeps explicit index names when a table is renamed. Drop only
        # those indexes now; automatic unique/primary-key indexes disappear with
        # the legacy table and cannot be dropped directly.
        indexes = conn.execute(text("PRAGMA index_list(file_tags_m0033_legacy)")).fetchall()
        for index in indexes:
            index_name = str(index[1])
            if not index_name.startswith("sqlite_autoindex_"):
                conn.execute(text(f"DROP INDEX IF EXISTS {_identifier(index_name)}"))
        _create_file_tags(conn)
        for row in prepared:
            conn.execute(
                text(
                    "INSERT INTO file_tags "
                    "(id,path,location_id,normalized_path,tags,color,starred,created_at) "
                    "VALUES (:id,:path,:location_id,:normalized_path,:tags,:color,:starred,:created_at)"
                ),
                row,
            )
        conn.execute(text("DROP TABLE file_tags_m0033_legacy"))
        return

    for row in prepared:
        conn.execute(
            text(
                "UPDATE file_tags SET location_id=:location_id, normalized_path=:normalized_path "
                "WHERE id=:id AND (location_id IS NULL OR location_id='' OR "
                "normalized_path IS NULL OR normalized_path='')"
            ),
            row,
        )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_file_tags_location_path "
            "ON file_tags(location_id,normalized_path)"
        )
    )


def _add_identity_columns(conn, table: str) -> None:
    add_column(conn, table, "location_id", "VARCHAR")
    add_column(conn, table, "normalized_path", "VARCHAR")
    conn.execute(
        text(f'CREATE INDEX IF NOT EXISTS "ix_{table}_location_id" ON "{table}"(location_id)')
    )
    conn.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS "ix_{table}_normalized_path" ON "{table}"(normalized_path)'
        )
    )


def _backfill_path_table(conn, table: str, *, allow_root: bool = False) -> int:
    rows = conn.execute(
        text(f'SELECT id,path,location_id,normalized_path FROM "{table}" ORDER BY id')
    ).mappings()
    count = 0
    for row in rows:
        normalized = _normalize(
            row["normalized_path"] or row["path"],
            table=table,
            row_id=str(row["id"]),
            allow_root=allow_root,
        )
        location_id = row["location_id"] or DEFAULT_LOCATION_ID
        if row["location_id"] != location_id or row["normalized_path"] != normalized:
            conn.execute(
                text(
                    f'UPDATE "{table}" SET location_id=:location_id, '
                    "normalized_path=:normalized_path WHERE id=:id"
                ),
                {
                    "id": row["id"],
                    "location_id": location_id,
                    "normalized_path": normalized,
                },
            )
        count += 1
    return count


def _backfill_ref_table(
    conn, table: str, kind_column: str, kind_value, *, allow_root: bool = False
) -> int:
    kinds = (kind_value,) if isinstance(kind_value, str) else tuple(kind_value)
    params = {f"kind_{index}": value for index, value in enumerate(kinds)}
    placeholders = ",".join(f":kind_{index}" for index in range(len(kinds)))
    rows = conn.execute(
        text(
            f'SELECT id,ref,location_id,normalized_path FROM "{table}" '
            f'WHERE "{kind_column}" IN ({placeholders}) ORDER BY id'
        ),
        params,
    ).mappings()
    count = 0
    for row in rows:
        normalized = _normalize(
            row["normalized_path"] or row["ref"],
            table=table,
            row_id=str(row["id"]),
            allow_root=allow_root,
        )
        location_id = row["location_id"] or DEFAULT_LOCATION_ID
        if row["location_id"] != location_id or row["normalized_path"] != normalized:
            conn.execute(
                text(
                    f'UPDATE "{table}" SET location_id=:location_id, '
                    "normalized_path=:normalized_path WHERE id=:id"
                ),
                {
                    "id": row["id"],
                    "location_id": location_id,
                    "normalized_path": normalized,
                },
            )
        count += 1
    return count


def _verify_identity_count(
    conn, table: str, expected: int, where: str = "", *, allow_root: bool = False
) -> None:
    clause = f" WHERE {where}" if where else ""
    path_check = "normalized_path IS NOT NULL"
    if not allow_root:
        path_check += " AND normalized_path != ''"
    actual = conn.execute(
        text(
            f'SELECT COUNT(*) FROM "{table}"{clause} AND '
            "location_id IS NOT NULL AND location_id != '' AND "
            f"{path_check}"
            if clause
            else f'SELECT COUNT(*) FROM "{table}" WHERE '
            "location_id IS NOT NULL AND location_id != '' AND "
            f"{path_check}"
        )
    ).scalar_one()
    if actual != expected:
        raise RuntimeError(f"Files identity audit failed for {table}: {actual} != {expected}")


def up(conn):
    _create_location_tables(conn)
    tables = _tables(conn)
    # Preserve empty-database migrations as schema-only. Files calls
    # storage_locations.ensure_default_local() before every default-location lookup or mutation;
    # this migration row exists only to own identities that are already present and need backfill.
    if _needs_default_location(conn, tables):
        _ensure_default_location(conn)
    _migrate_file_tags(conn, tables)
    tables = _tables(conn)

    counts = {"file_tags": conn.execute(text("SELECT COUNT(*) FROM file_tags")).scalar_one()}
    for table in ("file_versions", "file_comments"):
        if table not in tables:
            continue
        _add_identity_columns(conn, table)
        counts[table] = _backfill_path_table(conn, table, allow_root=table == "file_comments")

    for table, kind_column, kind_value, count_name in (
        ("trash_items", "kind", "file", "file_trash_items"),
        ("shares", "kind", ("file", "folder"), "file_shares"),
        ("index_chunks", "kind", "file", "file_index_chunks"),
    ):
        if table not in tables:
            continue
        _add_identity_columns(conn, table)
        counts[count_name] = _backfill_ref_table(
            conn,
            table,
            kind_column,
            kind_value,
            allow_root=table == "shares",
        )

    _verify_identity_count(conn, "file_tags", counts["file_tags"], allow_root=True)
    if "file_versions" in counts:
        _verify_identity_count(conn, "file_versions", counts["file_versions"])
    if "file_comments" in counts:
        _verify_identity_count(conn, "file_comments", counts["file_comments"], allow_root=True)
    if "file_trash_items" in counts:
        _verify_identity_count(conn, "trash_items", counts["file_trash_items"], "kind='file'")
    if "file_shares" in counts:
        _verify_identity_count(
            conn,
            "shares",
            counts["file_shares"],
            "kind IN ('file','folder')",
            allow_root=True,
        )
    if "file_index_chunks" in counts:
        _verify_identity_count(conn, "index_chunks", counts["file_index_chunks"], "kind='file'")

    conn.execute(
        text(
            "INSERT OR IGNORE INTO storage_location_migration_audits "
            "(id,location_id,counts_json,created_at) VALUES "
            "('m0033-default-local',:location_id,:counts,:created_at)"
        ),
        {
            "location_id": DEFAULT_LOCATION_ID,
            "counts": json.dumps(counts, sort_keys=True, separators=(",", ":")),
            "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        },
    )

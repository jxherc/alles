"""m0052 - Health record identities and CSV batch acknowledgments."""

import uuid

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 52
NAME = "health_import_identity"


def up(conn):
    add_column(conn, "health_entries", "record_id", "TEXT")
    missing = (
        conn.execute(
            text("SELECT id FROM health_entries WHERE record_id IS NULL OR record_id = ''")
        )
        .scalars()
        .all()
    )
    if missing:
        conn.execute(
            text("UPDATE health_entries SET record_id = :record_id WHERE id = :id"),
            [{"id": eid, "record_id": str(uuid.uuid4())} for eid in missing],
        )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_health_entries_record_id "
            "ON health_entries (record_id)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS health_import_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, payload_hash TEXT NOT NULL, "
            "imported INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0, "
            "created_at DATETIME)"
        )
    )

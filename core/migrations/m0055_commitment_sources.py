"""m0055 - reviewed commitment sources and durable acceptance identities."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 55
NAME = "commitment_sources"


def up(conn):
    add_column(conn, "tasks", "source_json", "TEXT DEFAULT '{}'")
    add_column(conn, "calendar_events", "source_json", "TEXT DEFAULT '{}'")
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS commitment_create_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, payload_hash TEXT NOT NULL, "
            "resource_id TEXT, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_commitment_create_receipts_resource_id "
            "ON commitment_create_receipts (resource_id)"
        )
    )

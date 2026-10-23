"""m0049 - Health create acknowledgments, including deletion tombstones."""

from sqlalchemy import text

VERSION = 49
NAME = "health_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS health_create_receipts ("
            "id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, entry_id INTEGER, "
            "created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_health_create_receipts_entry_id "
            "ON health_create_receipts (entry_id)"
        )
    )

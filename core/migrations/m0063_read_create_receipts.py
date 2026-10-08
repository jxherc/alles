"""Retain ordinary saved-URL request identities after article deletion."""

from sqlalchemy import text

VERSION = 63
NAME = "read_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS read_create_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, payload_hash TEXT NOT NULL, "
            "item_id TEXT NOT NULL, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_read_create_receipts_item_id "
            "ON read_create_receipts (item_id)"
        )
    )

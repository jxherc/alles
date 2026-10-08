"""Retain saved-search identities without retaining deleted search content."""

from sqlalchemy import text

VERSION = 66
NAME = "andromeda_save_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS andromeda_save_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, payload_hash TEXT NOT NULL, "
            "search_id TEXT NOT NULL, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_andromeda_save_receipts_search_id "
            "ON andromeda_save_receipts (search_id)"
        )
    )

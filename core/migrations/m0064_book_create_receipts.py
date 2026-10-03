"""Retain book creation identities without keeping deleted book content."""

from sqlalchemy import text

VERSION = 64
NAME = "book_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS book_create_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, payload_hash TEXT NOT NULL, "
            "book_id TEXT NOT NULL, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_book_create_receipts_book_id "
            "ON book_create_receipts (book_id)"
        )
    )

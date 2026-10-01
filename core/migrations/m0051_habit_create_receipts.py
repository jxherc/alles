"""m0051 - Retry identities for habit creation, including deletion tombstones."""

from sqlalchemy import text

VERSION = 51
NAME = "habit_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS habit_create_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, habit_id TEXT, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_habit_create_receipts_habit_id "
            "ON habit_create_receipts (habit_id)"
        )
    )

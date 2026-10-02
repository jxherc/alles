"""m0054 - content-free retry identities for reminder creation."""

from sqlalchemy import text

VERSION = 54
NAME = "reminder_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS reminder_create_receipts ("
            "id TEXT PRIMARY KEY NOT NULL, reminder_id TEXT, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_reminder_create_receipts_reminder_id "
            "ON reminder_create_receipts (reminder_id)"
        )
    )

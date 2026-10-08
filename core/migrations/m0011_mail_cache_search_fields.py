"""m0011 - cache recipient + attachment flags for mail advanced search."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 11
NAME = "mail_cache_search_fields"


def up(conn):
    add_column(conn, "cached_messages", "recipients", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "has_attachment", "BOOLEAN DEFAULT 0")


def down(conn):
    for col in ("recipients", "has_attachment"):
        conn.execute(text(f'ALTER TABLE cached_messages DROP COLUMN "{col}"'))

"""Keep a reading place in the existing saved-article record."""

from core.migrations.runner import add_column

VERSION = 62
NAME = "reading_position"


def up(conn):
    add_column(conn, "read_items", "read_position", "REAL NOT NULL DEFAULT 0")

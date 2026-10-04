"""Order final reading-place writes without changing existing positions."""

from core.migrations.runner import add_column

VERSION = 67
NAME = "reading_position_revision"


def up(conn):
    add_column(conn, "read_items", "position_revision", "TEXT NOT NULL DEFAULT ''")

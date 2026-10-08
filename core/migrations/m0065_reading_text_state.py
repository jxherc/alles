"""Distinguish extracted article text without guessing the origin of older text."""

from core.migrations.runner import add_column

VERSION = 65
NAME = "reading_text_state"


def up(conn):
    add_column(conn, "read_items", "text_state", "TEXT NOT NULL DEFAULT 'unknown'")

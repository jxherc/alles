"""m0031 - per-conversation Aide behavior override."""

from core.migrations.runner import add_column

VERSION = 31
NAME = "aide_conversation"


def up(conn):
    add_column(conn, "sessions", "chat_behavior", "TEXT NOT NULL DEFAULT ''")

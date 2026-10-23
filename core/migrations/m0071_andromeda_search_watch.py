"""m0071 - saved Andromeda searches can be watched for new links."""

from core.migrations.runner import add_column

VERSION = 71
NAME = "andromeda_search_watch"


def up(conn):
    for column, kind in (
        ("watch_every_hours", "INTEGER NOT NULL DEFAULT 0"),
        ("watch_next_at", "DATETIME"),
        ("watch_checked_at", "DATETIME"),
        ("watch_seen_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("watch_new_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("watch_error", "VARCHAR NOT NULL DEFAULT ''"),
    ):
        add_column(conn, "andromeda_saved_searches", column, kind)

"""m0032 - reopenable Andromeda search snapshots."""

from sqlalchemy import text

VERSION = 32
NAME = "andromeda_saved_searches"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS andromeda_saved_searches ("
            "id VARCHAR PRIMARY KEY, query TEXT NOT NULL, request_json TEXT NOT NULL DEFAULT '{}', "
            "results_json TEXT NOT NULL DEFAULT '[]', overview_json TEXT NOT NULL DEFAULT '{}', "
            "evidence_json TEXT NOT NULL DEFAULT '[]', model_json TEXT NOT NULL DEFAULT '{}', "
            "checked_at DATETIME, created_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_andromeda_saved_searches_created_at "
            "ON andromeda_saved_searches(created_at)"
        )
    )

"""m0023 - memory scope, review state, provenance trust, and usage records."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 23
NAME = "memory_policy"


def up(conn):
    add_column(conn, "memories", "scope", "TEXT NOT NULL DEFAULT 'global'")
    add_column(conn, "memories", "project_id", "TEXT")
    add_column(conn, "memories", "status", "TEXT NOT NULL DEFAULT 'active'")
    add_column(conn, "memories", "trust", "TEXT NOT NULL DEFAULT 'owner'")
    add_column(conn, "memories", "updated_at", "DATETIME")
    add_column(conn, "memories", "used_in_runs", "TEXT NOT NULL DEFAULT '[]'")
    conn.execute(text("UPDATE memories SET updated_at = timestamp WHERE updated_at IS NULL"))
    conn.execute(
        text("UPDATE memories SET status = 'suggested', trust = 'derived' WHERE source != 'manual'")
    )

"""Give Aide one durable primary conversation without rewriting history."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 68
NAME = "aide_primary_session"


def up(conn):
    add_column(conn, "sessions", "aide_role", "TEXT NOT NULL DEFAULT ''")
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_aide_primary "
            "ON sessions(aide_role) WHERE aide_role = 'primary'"
        )
    )


def down(conn):
    # Keep the additive column and its values. Older code ignores them, while a
    # later upgrade can restore the primary identity without losing history.
    conn.execute(text("DROP INDEX IF EXISTS ux_sessions_aide_primary"))

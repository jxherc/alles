"""Keep removed account identities and protect configuration updates."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 60
NAME = "mail_account_recovery"


def up(conn):
    add_column(conn, "mail_accounts", "revision", "INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS mail_account_deletions ("
            "id TEXT NOT NULL PRIMARY KEY, deleted_at DATETIME NOT NULL)"
        )
    )

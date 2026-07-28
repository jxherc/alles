from sqlalchemy import text

VERSION = 40
NAME = "browser_connections"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS browser_connections ("
            "id VARCHAR PRIMARY KEY, "
            "vault_id VARCHAR NOT NULL DEFAULT 'default', "
            "name VARCHAR NOT NULL DEFAULT 'Browser', "
            "secret_hash VARCHAR NOT NULL, "
            "extension_origin VARCHAR NOT NULL, "
            "created_at DATETIME, "
            "last_seen_at DATETIME, "
            "revoked_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_browser_connections_vault "
            "ON browser_connections(vault_id, revoked_at)"
        )
    )

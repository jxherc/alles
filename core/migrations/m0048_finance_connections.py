"""m0048 - encrypted read-only Finance aggregator connections."""

from sqlalchemy import text

VERSION = 48
NAME = "finance_connections"


def up(conn):
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS finance_connections (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT 'bank connection',
                environment TEXT NOT NULL DEFAULT 'production',
                status TEXT NOT NULL DEFAULT 'connected',
                client_id TEXT NOT NULL DEFAULT '',
                client_secret TEXT NOT NULL DEFAULT '',
                access_token TEXT NOT NULL DEFAULT '',
                item_id TEXT NOT NULL DEFAULT '',
                cursor TEXT NOT NULL DEFAULT '',
                account_map_json TEXT NOT NULL DEFAULT '{}',
                consent_expires_at DATETIME,
                last_synced_at DATETIME,
                last_error TEXT NOT NULL DEFAULT '',
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_finance_connections_provider "
            "ON finance_connections (provider)"
        )
    )

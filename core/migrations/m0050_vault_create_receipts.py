"""m0050 - Vault create identities without duplicated secrets or fingerprints."""

from sqlalchemy import text

VERSION = 50
NAME = "vault_create_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS vault_create_receipts ("
            "vault_id TEXT NOT NULL, id TEXT NOT NULL, entry_id TEXT, "
            "created_at DATETIME, PRIMARY KEY (vault_id, id))"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_vault_create_receipts_entry_id "
            "ON vault_create_receipts (entry_id)"
        )
    )

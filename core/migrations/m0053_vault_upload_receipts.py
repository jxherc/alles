"""m0053 - content-free Vault attachment retry identities."""

from sqlalchemy import text

VERSION = 53
NAME = "vault_upload_receipts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS vault_upload_receipts ("
            "vault_id TEXT NOT NULL, id TEXT NOT NULL, attachment_id TEXT, "
            "created_at DATETIME, PRIMARY KEY (vault_id, id))"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_vault_upload_receipts_attachment_id "
            "ON vault_upload_receipts (attachment_id)"
        )
    )

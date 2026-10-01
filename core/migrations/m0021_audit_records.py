"""m0021 - durable audit records for owner-visible state changes."""

from sqlalchemy import text

VERSION = 21
NAME = "audit_records"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS audit_records ("
            "id TEXT PRIMARY KEY, action TEXT NOT NULL, outcome TEXT NOT NULL, "
            "actor TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '', "
            "request_id TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '{}', "
            "created_at DATETIME)"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_audit_records_action ON audit_records(action)")
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_audit_records_created_at ON audit_records(created_at)")
    )

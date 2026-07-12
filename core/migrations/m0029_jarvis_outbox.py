"""m0029 - make Jarvis delivery attempts a lease-safe outbox."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 29
NAME = "jarvis_outbox"


def up(conn):
    add_column(conn, "jarvis_delivery_attempts", "connector_id", "VARCHAR")
    add_column(conn, "jarvis_delivery_attempts", "lease_owner", "VARCHAR DEFAULT ''")
    add_column(conn, "jarvis_delivery_attempts", "lease_expires_at", "DATETIME")
    add_column(conn, "jarvis_delivery_attempts", "idempotency_supported", "BOOLEAN DEFAULT 0")
    add_column(conn, "jarvis_delivery_attempts", "last_attempt_at", "DATETIME")
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_jarvis_delivery_attempts_connector_id "
            "ON jarvis_delivery_attempts(connector_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_jarvis_delivery_attempts_lease_expires_at "
            "ON jarvis_delivery_attempts(lease_expires_at)"
        )
    )

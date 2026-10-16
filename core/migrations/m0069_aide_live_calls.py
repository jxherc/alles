"""Durable live-call identity and finalized transcript event receipts."""

from sqlalchemy import text

VERSION = 69
NAME = "aide_live_calls"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS aide_calls ("
            "id VARCHAR PRIMARY KEY NOT NULL, "
            "session_id VARCHAR NOT NULL, "
            "provider VARCHAR NOT NULL DEFAULT 'openai-realtime', "
            "model VARCHAR NOT NULL DEFAULT '', "
            "state VARCHAR NOT NULL DEFAULT 'connecting', "
            "provider_call_id VARCHAR DEFAULT '', "
            "created_at DATETIME, connected_at DATETIME, ended_at DATETIME, updated_at DATETIME, "
            "FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS aide_call_events ("
            "id VARCHAR PRIMARY KEY NOT NULL, "
            "call_id VARCHAR NOT NULL, sequence INTEGER NOT NULL, kind VARCHAR NOT NULL, "
            "role VARCHAR DEFAULT '', text TEXT DEFAULT '', provider_event_id VARCHAR, "
            "data TEXT DEFAULT '{}', created_at DATETIME, "
            "FOREIGN KEY(call_id) REFERENCES aide_calls(id) ON DELETE CASCADE)"
        )
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_aide_calls_state ON aide_calls(state)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_aide_call_events_sequence "
        "ON aide_call_events(call_id, sequence)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_aide_call_events_provider_event "
        "ON aide_call_events(call_id, provider_event_id)",
    ):
        conn.execute(text(statement))


def down(conn):
    conn.execute(text("DROP INDEX IF EXISTS ux_aide_call_events_provider_event"))
    conn.execute(text("DROP INDEX IF EXISTS ux_aide_call_events_sequence"))
    conn.execute(text("DROP INDEX IF EXISTS ix_aide_calls_state"))
    conn.execute(text("DROP TABLE IF EXISTS aide_call_events"))
    conn.execute(text("DROP TABLE IF EXISTS aide_calls"))

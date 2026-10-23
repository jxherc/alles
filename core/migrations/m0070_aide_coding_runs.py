"""Encrypted DSH bridge connection and durable Aide coding-run receipts."""

from sqlalchemy import text

VERSION = 70
NAME = "aide_coding_runs"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS dsh_connections ("
            "id VARCHAR PRIMARY KEY NOT NULL, base_url VARCHAR NOT NULL, token TEXT NOT NULL, "
            "host_version VARCHAR DEFAULT '', connected_at DATETIME, checked_at DATETIME, "
            "updated_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS aide_coding_runs ("
            "id VARCHAR PRIMARY KEY NOT NULL, aide_session_id VARCHAR, workspace_id VARCHAR NOT NULL, "
            "workspace_path TEXT DEFAULT '', provider_session_id VARCHAR NOT NULL, prompt TEXT NOT NULL, "
            "prompt_hash VARCHAR NOT NULL, state VARCHAR NOT NULL DEFAULT 'starting', "
            "error_code VARCHAR DEFAULT '', safe_error TEXT DEFAULT '', created_at DATETIME, "
            "updated_at DATETIME, finished_at DATETIME, "
            "FOREIGN KEY(aide_session_id) REFERENCES sessions(id) ON DELETE SET NULL)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS aide_coding_run_events ("
            "id VARCHAR PRIMARY KEY NOT NULL, run_id VARCHAR NOT NULL, sequence INTEGER NOT NULL, "
            "kind VARCHAR NOT NULL, summary TEXT NOT NULL, data TEXT DEFAULT '{}', created_at DATETIME, "
            "FOREIGN KEY(run_id) REFERENCES aide_coding_runs(id) ON DELETE CASCADE)"
        )
    )
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_aide_coding_runs_provider_session "
        "ON aide_coding_runs(provider_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_aide_coding_runs_state ON aide_coding_runs(state)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_aide_coding_run_events_sequence "
        "ON aide_coding_run_events(run_id, sequence)",
    ):
        conn.execute(text(statement))


def down(conn):
    conn.execute(text("DROP INDEX IF EXISTS ux_aide_coding_run_events_sequence"))
    conn.execute(text("DROP INDEX IF EXISTS ix_aide_coding_runs_state"))
    conn.execute(text("DROP INDEX IF EXISTS ux_aide_coding_runs_provider_session"))
    conn.execute(text("DROP TABLE IF EXISTS aide_coding_run_events"))
    conn.execute(text("DROP TABLE IF EXISTS aide_coding_runs"))
    conn.execute(text("DROP TABLE IF EXISTS dsh_connections"))

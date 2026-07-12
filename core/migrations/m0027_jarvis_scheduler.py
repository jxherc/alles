"""m0027 - add lease-safe scheduling fields and unique occurrences."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 27
NAME = "jarvis_scheduler"


def up(conn):
    add_column(conn, "jarvis_workflows", "active_run_id", "VARCHAR")
    add_column(conn, "jarvis_runs", "next_attempt_at", "DATETIME")
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_jarvis_workflows_active_run_id "
            "ON jarvis_workflows(active_run_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_jarvis_runs_next_attempt_at "
            "ON jarvis_runs(next_attempt_at)"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_jarvis_runs_trigger_occurrence "
            "ON jarvis_runs(trigger_id,occurrence_key)"
        )
    )

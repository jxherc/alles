"""Remember issued task occurrences without guessing successor identities."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 61
NAME = "task_recurrence_history"


def up(conn):
    if add_column(conn, "tasks", "recurrence_issued", "BOOLEAN NOT NULL DEFAULT 0"):
        # Completed legacy recurrences may already have an edited/deleted successor.
        # Active legacy rows have no reliable history; never infer it from title/date.
        conn.execute(
            text(
                "UPDATE tasks SET recurrence_issued = 1 WHERE done = 1 "
                "AND COALESCE(repeat, '') != '' AND COALESCE(due_date, '') != ''"
            )
        )

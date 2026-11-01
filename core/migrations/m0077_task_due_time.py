"""m0077 - a task's due date can carry a time.

tasks.due_time: "HH:MM" on the due day, or null for a task that is due any time that day.
a task due at a time goes overdue at that time, not at midnight. a few rows were saved by older
clients with the time inside due_date ("2026-10-20T09:30"); those are split into the two
columns here so every reader sees one shape.

existing tasks keep a null due_time, so they read exactly as before. running it again changes
nothing.
"""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 77
NAME = "task_due_time"


def up(conn):
    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "tasks" not in have:
        return
    add_column(conn, "tasks", "due_time", "VARCHAR")
    rows = conn.execute(
        text("SELECT id, due_date FROM tasks WHERE length(due_date) > 10 AND due_date LIKE '%T%'")
    ).fetchall()
    for task_id, due in rows:
        day, _, clock = str(due).partition("T")
        clock = clock[:5]
        valid = len(clock) == 5 and clock[2] == ":"
        conn.execute(
            text("UPDATE tasks SET due_date = :day, due_time = :clock WHERE id = :id"),
            {"day": day, "clock": clock if valid else None, "id": task_id},
        )

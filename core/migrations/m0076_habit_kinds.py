"""m0076 - habits get a type, and a day's log can carry details.

habits.kind: what the day's log holds. "check" (the old tap-to-mark habit), "workout", "reading",
"count", "duration" or "distance". habits.unit: the count habit's unit (glasses, steps, ...).
habit_logs.data: json with that day's details (sets and weights, pages read, minutes). a row
still means "done that day"; data is null for a plain check.

existing habits become "check" with no unit and existing logs keep null data, so they read
exactly as before. running it again changes nothing.
"""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 76
NAME = "habit_kinds"


def up(conn):
    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "habits" in have:
        add_column(conn, "habits", "kind", "VARCHAR DEFAULT 'check'")
        add_column(conn, "habits", "unit", "VARCHAR DEFAULT ''")
        conn.execute(text("UPDATE habits SET kind = 'check' WHERE kind IS NULL OR kind = ''"))
        conn.execute(text("UPDATE habits SET unit = '' WHERE unit IS NULL"))
    if "habit_logs" in have:
        add_column(conn, "habit_logs", "data", "TEXT")

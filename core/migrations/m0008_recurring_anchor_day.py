"""m0008 - recurring day-of-month anchor. monthly/quarterly/yearly recurring txns and repeating
tasks used to drift their day-of-month DOWN after a short month (due 31 -> feb 28 -> mar 28 -> ...
stuck on 28) because each step advanced from the previously-clamped date. store the original
day-of-month so every occurrence clamps from the anchor, not the last clamped value. idempotent.

backfill picks the day component of the current next_date/due_date — best guess for existing rows
(a row already drifted locks in its current day, but stops drifting further from here)."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 8
NAME = "recurring_anchor_day"


def up(conn):
    add_column(conn, "money_recurring", "anchor_day", "INTEGER")
    conn.execute(text(
        "UPDATE money_recurring SET anchor_day = CAST(substr(next_date, 9, 2) AS INTEGER) "
        "WHERE anchor_day IS NULL AND length(next_date) >= 10"
    ))
    add_column(conn, "tasks", "anchor_day", "INTEGER")
    conn.execute(text(
        "UPDATE tasks SET anchor_day = CAST(substr(due_date, 9, 2) AS INTEGER) "
        "WHERE anchor_day IS NULL AND repeat != '' AND length(due_date) >= 10"
    ))


def down(conn):
    for t in ("money_recurring", "tasks"):
        conn.execute(text(f'ALTER TABLE {t} DROP COLUMN "anchor_day"'))

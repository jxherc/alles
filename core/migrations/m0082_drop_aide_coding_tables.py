"""m0082 - drop the coding run and dsh connection tables that nothing writes any more.

a table that still holds rows is left alone, so nothing the owner might want is lost.
"""

from sqlalchemy import text

VERSION = 82
NAME = "drop_aide_coding_tables"

# children first: the events table points at the runs table
TABLES = ("aide_coding_run_events", "aide_coding_runs", "dsh_connections")


def up(conn):
    for table in TABLES:
        exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table},
        ).first()
        if not exists:
            continue
        if conn.execute(text(f'SELECT 1 FROM "{table}" LIMIT 1')).first():
            continue
        conn.execute(text(f'DROP TABLE "{table}"'))

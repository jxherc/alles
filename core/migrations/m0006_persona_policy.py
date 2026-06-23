"""m0006 - 3b persona policy: add blocked_scopes + blocked_tools to personas so a persona can
restrict which tool scopes/names it may use (e.g. a code-reviewer that blocks shell). idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 6
NAME = "persona_policy"


def up(conn):
    add_column(conn, "personas", "blocked_scopes", "TEXT DEFAULT ''")
    add_column(conn, "personas", "blocked_tools", "TEXT DEFAULT ''")


def down(conn):
    for col in ("blocked_scopes", "blocked_tools"):
        conn.execute(text(f'ALTER TABLE personas DROP COLUMN "{col}"'))

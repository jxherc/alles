"""Separate scheduled News cadence from its active-run lease."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 43
NAME = "news_run_lease"


def up(conn):
    add_column(conn, "news_configuration", "run_token", "VARCHAR DEFAULT ''")
    add_column(conn, "news_configuration", "run_lease_until", "DATETIME")
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_news_configuration_run_lease "
            "ON news_configuration(run_lease_until)"
        )
    )

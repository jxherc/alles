"""Retain delivery intent metadata for safe retries."""

from core.migrations.runner import add_column

VERSION = 58
NAME = "mail_outbox_recovery"


def up(conn):
    add_column(conn, "mail_scheduled", "request_kind", "VARCHAR DEFAULT ''")
    add_column(conn, "mail_scheduled", "request_delay", "INTEGER")

"""Preserve deleted draft identities across uncertain save retries."""

from core.migrations.runner import add_column

VERSION = 57
NAME = "mail_draft_recovery"


def up(conn):
    add_column(conn, "mail_drafts", "deleted_at", "DATETIME")

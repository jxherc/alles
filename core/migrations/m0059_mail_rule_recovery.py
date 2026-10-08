"""Retain deleted rule identities so late creation retries cannot revive them."""

from core.migrations.runner import add_column

VERSION = 59
NAME = "mail_rule_recovery"


def up(conn):
    add_column(conn, "mail_rules", "deleted_at", "DATETIME")

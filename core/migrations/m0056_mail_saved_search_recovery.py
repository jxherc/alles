"""Keep deleted mail search identities so a delayed save cannot recreate them."""

from core.migrations.runner import add_column

VERSION = 56
NAME = "mail_saved_search_recovery"


def up(conn):
    add_column(conn, "mail_saved_searches", "deleted_at", "DATETIME")

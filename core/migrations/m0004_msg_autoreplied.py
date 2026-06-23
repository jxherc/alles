"""m0004 - 2g mail rule autoreply guard: add `autoreplied` to cached_messages so re-running rules
never re-enqueues a reply for a message already answered. add_column is idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 4
NAME = "msg_autoreplied"


def up(conn):
    add_column(conn, "cached_messages", "autoreplied", "BOOLEAN DEFAULT 0")


def down(conn):
    conn.execute(text('ALTER TABLE cached_messages DROP COLUMN "autoreplied"'))

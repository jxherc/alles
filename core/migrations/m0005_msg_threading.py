"""m0005 - 2i RFC-5322 threading: add the reference-graph headers + thread_id to cached_messages
so replies thread by Message-ID/References instead of by subject. add_column is idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 5
NAME = "msg_threading"


def up(conn):
    add_column(conn, "cached_messages", "message_id", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "in_reply_to", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "references", "TEXT DEFAULT ''")
    add_column(conn, "cached_messages", "thread_id", "TEXT DEFAULT ''")


def down(conn):
    for col in ("message_id", "in_reply_to", "references", "thread_id"):
        conn.execute(text(f'ALTER TABLE cached_messages DROP COLUMN "{col}"'))

"""m0081 - messages sent while aide is still replying wait in their own table."""

from sqlalchemy import text

VERSION = 81
NAME = "queued_messages"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS queued_messages ("
            "id VARCHAR PRIMARY KEY NOT NULL, session_id VARCHAR NOT NULL, "
            "content TEXT NOT NULL DEFAULT '', file_ids TEXT DEFAULT '[]', created_at DATETIME, "
            "FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_queued_messages_session_id "
            "ON queued_messages (session_id)"
        )
    )

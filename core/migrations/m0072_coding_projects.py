"""m0072 - folders that pi coding chats run in."""

from sqlalchemy import text

VERSION = 72
NAME = "coding_projects"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS coding_projects ("
            "id VARCHAR PRIMARY KEY NOT NULL, path TEXT NOT NULL UNIQUE, name VARCHAR NOT NULL, "
            "created_at DATETIME, last_used_at DATETIME)"
        )
    )

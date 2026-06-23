"""m0007 - 4c shareable links: add expiry + password to the shares table so a published link can
expire and/or require a password. idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 7
NAME = "share_expiry_pw"


def up(conn):
    add_column(conn, "shares", "expires_at", "TEXT DEFAULT ''")
    add_column(conn, "shares", "password_hash", "TEXT DEFAULT ''")


def down(conn):
    for col in ("expires_at", "password_hash"):
        conn.execute(text(f'ALTER TABLE shares DROP COLUMN "{col}"'))

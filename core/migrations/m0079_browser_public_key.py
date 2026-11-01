"""m0079 - a paired browser keeps the public half of its own key pair.

browser_connections.public_key: the extension's ecdh p-256 public key (raw point, base64url),
sent when it asks to pair. every login, card or address the server releases to that browser
is sealed to this key, so only the extension that holds the private half can read it.

browsers paired before this have no key; they are asked to pair again instead of getting
plain fills. running it again changes nothing.
"""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 79
NAME = "browser_public_key"


def up(conn):
    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "browser_connections" not in have:
        return
    add_column(conn, "browser_connections", "public_key", "TEXT")

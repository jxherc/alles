"""m0024 - wrap legacy public-share SHA-256 hashes in bcrypt."""

import hashlib

from sqlalchemy import text

from core.auth import hash_password

VERSION = 24
NAME = "share_password_hashes"

_PREFIX = "legacy-bcrypt:"


def _is_legacy_hash(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def up(conn):
    rows = list(conn.execute(text("SELECT id,password_hash FROM shares WHERE password_hash != ''")))
    for share_id, stored in rows:
        value = str(stored or "")
        if not _is_legacy_hash(value):
            continue
        material = hashlib.sha256(("alles-share-legacy:" + value.lower()).encode()).hexdigest()
        wrapped = _PREFIX + hash_password(material)
        conn.execute(
            text(
                "UPDATE shares SET password_hash=:wrapped "
                "WHERE id=:share_id AND password_hash=:legacy"
            ),
            {"wrapped": wrapped, "share_id": share_id, "legacy": stored},
        )

"""m0010 - retire the legacy `notes` table. notes live in the markdown vault now; m0009
(runs just before this, same boot) copies every row into Notes/*.md. this drops the table
only after confirming every row made it to the vault (safety), so a misconfigured vault can't
lose data. reversible: down() rebuilds the table from the vault files.
"""

from sqlalchemy import text

from core.migrations.runner import MigrationBlockedError

VERSION = 10
NAME = "drop_note_table"


def up(conn):
    have = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "notes" not in have:
        return
    row_ids = {r[0] for r in conn.execute(text("SELECT id FROM notes"))}
    if row_ids:
        # only drop if every db note is present in the vault (matched by legacy_id)
        from services import notes_vault

        if not row_ids.issubset(notes_vault.existing_legacy_ids()):
            raise MigrationBlockedError(
                "legacy notes are not fully present in the Markdown vault; refusing to drop them"
            )
    conn.execute(text("DROP TABLE IF EXISTS notes"))


def down(conn):
    """rebuild the table + repopulate from the vault (best-effort undo)."""
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS notes ("
            "id TEXT PRIMARY KEY, title TEXT DEFAULT '', content TEXT DEFAULT '', "
            "pinned BOOLEAN DEFAULT 0, archived BOOLEAN DEFAULT 0, tags TEXT DEFAULT '', "
            "items TEXT DEFAULT '[]', due TEXT DEFAULT '', created_at DATETIME, updated_at DATETIME)"
        )
    )
    try:
        import json

        from services import notes_vault

        for n in notes_vault.all_notes():
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO notes "
                    "(id,title,content,pinned,archived,tags,items,due,created_at,updated_at) "
                    "VALUES (:id,:t,:c,:p,:a,:tg,:it,:d,:ca,:ua)"
                ),
                {
                    "id": notes_vault._legacy(n["id"]) or n["id"],
                    "t": n["title"],
                    "c": n["content"],
                    "p": n["pinned"],
                    "a": n["archived"],
                    "tg": ",".join(n["tags"]),
                    "it": json.dumps(n["items"]),
                    "d": n["due"],
                    "ca": n["created_at"],
                    "ua": n["updated_at"],
                },
            )
    except Exception:
        pass

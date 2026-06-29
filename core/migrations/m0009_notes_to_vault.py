"""m0009 - move notes out of the `notes` table into markdown files under the vault's Notes/
folder, so the notes app is just a view over the Obsidian-compatible vault.

ADDITIVE + idempotent: it writes one Notes/<title>.md per row (carrying a `legacy_id`
frontmatter key) but does NOT touch the `notes` table — the DB stays as a live backup until
a later, gated migration drops it. Re-running skips rows already written (matched by legacy_id).

reads rows with raw SQL (not the ORM) so it keeps working after the Note model is removed.
"""

from sqlalchemy import text

VERSION = 9
NAME = "notes_to_vault"

_COLS = "id, title, content, pinned, archived, tags, items, due, created_at"


def up(conn):
    # table may not exist on a brand-new db that never created the notes table (it does via
    # create_all, but guard anyway so the migration can't hard-fail a fresh install)
    have = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "notes" not in have:
        return

    from services import notes_vault

    done = notes_vault.existing_legacy_ids()
    rows = conn.execute(text(f"SELECT {_COLS} FROM notes")).fetchall()
    for r in rows:
        nid = r[0]
        if nid in done:
            continue  # already migrated
        notes_vault.migrate_note(
            title=r[1] or "",
            content=r[2] or "",
            pinned=bool(r[3]),
            archived=bool(r[4]),
            tags=r[5] or "",
            items=r[6] or "[]",
            due=r[7] or "",
            created_iso=str(r[8]) if r[8] else None,
            legacy_id=nid,
        )

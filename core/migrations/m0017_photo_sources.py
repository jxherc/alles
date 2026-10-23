"""m0017 - stable source identity for native photo-library imports.

The partial unique index keeps repeated PhotoKit syncs idempotent while allowing
normal uploads (which have no source id) to coexist freely.
"""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 17
NAME = "photo_sources"


def up(conn):
    add_column(conn, "photos", "source", "TEXT")
    add_column(conn, "photos", "source_id", "TEXT")
    add_column(conn, "photos", "source_asset_id", "TEXT")
    add_column(conn, "photos", "source_modified_at", "DATETIME")
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_photos_source_id "
            "ON photos(source, source_id) WHERE source_id IS NOT NULL AND source_id != ''"
        )
    )
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_photos_source_asset_id ON photos(source_asset_id)")
    )


def down(conn):
    conn.execute(text("DROP INDEX IF EXISTS ux_photos_source_id"))
    conn.execute(text("DROP INDEX IF EXISTS ix_photos_source_id"))
    conn.execute(text("DROP INDEX IF EXISTS ix_photos_source"))
    conn.execute(text("DROP INDEX IF EXISTS ix_photos_source_asset_id"))
    for col in ("source_modified_at", "source_asset_id", "source_id", "source"):
        conn.execute(text(f'ALTER TABLE "photos" DROP COLUMN "{col}"'))

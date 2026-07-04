"""m0009 - photos archive flag. immich-style Archive: push an asset out of the main photos
timeline while keeping it in the library (albums, search). distinct from `hidden` (the vault-gated
locked folder) and from `deleted_at` (trash). idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 9
NAME = "photo_archive"


def up(conn):
    add_column(conn, "photos", "archived", "BOOLEAN DEFAULT 0")


def down(conn):
    conn.execute(text('ALTER TABLE "photos" DROP COLUMN "archived"'))

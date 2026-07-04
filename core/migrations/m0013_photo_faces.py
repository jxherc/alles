"""m0013 - face recognition (phase 7a). adds photos.faces_at (when detection last ran; null =
not scanned), and the people + faces tables. the tables themselves are created by
Base.metadata.create_all on boot — this migration only handles the new column on the existing
photos table. idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 13
NAME = "photo_faces"


def up(conn):
    add_column(conn, "photos", "faces_at", "DATETIME")


def down(conn):
    conn.execute(text('ALTER TABLE "photos" DROP COLUMN "faces_at"'))

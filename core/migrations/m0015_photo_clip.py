"""m0015 - CLIP embedding column for semantic search (phase 7b). a 512-float32 image embedding
(BLOB) per photo; filled by the background index job when the optional ML models are present.
null = not yet indexed; empty blob = indexing was attempted but failed (won't retry). idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 15
NAME = "photo_clip"


def up(conn):
    add_column(conn, "photos", "clip", "BLOB")


def down(conn):
    conn.execute(text('ALTER TABLE "photos" DROP COLUMN "clip"'))

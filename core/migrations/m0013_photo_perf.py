"""m0013 - photos perf fields. aspect_ratio (served so the justified grid needn't recompute),
preview (a tiny base64 jpeg the browser upscales into a blur-up placeholder), and checksum
(sha256 of the original bytes, for dedupe in phase 6). backfilled at startup. idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 13
NAME = "photo_perf"


def up(conn):
    add_column(conn, "photos", "aspect_ratio", "REAL")
    add_column(conn, "photos", "preview", "TEXT DEFAULT ''")
    add_column(conn, "photos", "checksum", "TEXT")


def down(conn):
    for col in ("aspect_ratio", "preview", "checksum"):
        conn.execute(text(f'ALTER TABLE "photos" DROP COLUMN "{col}"'))

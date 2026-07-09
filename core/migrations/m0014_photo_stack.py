"""m0014 - photo stacks. group related shots (a burst, edits, RAW+JPG) under one cover so the
timeline shows a single tile. stack_id = the cover photo's id, shared by every member (the cover's
stack_id == its own id); null = not stacked. idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 14
NAME = "photo_stack"


def up(conn):
    add_column(conn, "photos", "stack_id", "TEXT")


def down(conn):
    conn.execute(text('ALTER TABLE "photos" DROP COLUMN "stack_id"'))

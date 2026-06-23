"""m0002 - 1c memory auto-distillation: add confidence / vetoed / provenance to the existing
`memories` table. first numbered migration beyond the baseline; runs once, recorded in
schema_migrations. add_column is idempotent + surfaces real errors."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 2
NAME = "memory_distill"


def up(conn):
    add_column(conn, "memories", "confidence", "FLOAT DEFAULT 1.0")
    add_column(conn, "memories", "vetoed", "BOOLEAN DEFAULT 0")
    add_column(conn, "memories", "provenance", "TEXT DEFAULT ''")


def down(conn):
    # sqlite >= 3.35 supports DROP COLUMN
    for col in ("confidence", "vetoed", "provenance"):
        conn.execute(text(f'ALTER TABLE memories DROP COLUMN "{col}"'))

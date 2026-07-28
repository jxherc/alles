"""m0039 - reviewed per-row conversion evidence for canonical Finance imports."""

from sqlalchemy import text

from .runner import add_column

VERSION = 39
NAME = "finance_import_conversion_evidence"


def up(conn):
    tables = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "finance_import_rows" in tables:
        add_column(conn, "finance_import_rows", "conversion_json", "TEXT DEFAULT '{}'")

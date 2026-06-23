"""m0003 - 2e tag budgets: add a `tag` column to the existing money_budgets table so a budget
can cap a tag (hierarchy-rolled) instead of a category. add_column is idempotent."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 3
NAME = "budget_tag"


def up(conn):
    add_column(conn, "money_budgets", "tag", "TEXT DEFAULT ''")


def down(conn):
    conn.execute(text('ALTER TABLE money_budgets DROP COLUMN "tag"'))

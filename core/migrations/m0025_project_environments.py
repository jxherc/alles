"""m0025 - add folder Project metadata and compatible task stages."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 25
NAME = "project_environments"


def up(conn):
    add_column(conn, "projects", "scratchpad", "TEXT DEFAULT ''")
    add_column(conn, "projects", "last_opened_at", "DATETIME")
    add_column(conn, "tasks", "stage", "TEXT DEFAULT 'backlog'")
    conn.execute(
        text(
            "UPDATE projects SET scratchpad=description "
            "WHERE (scratchpad IS NULL OR scratchpad='') AND description IS NOT NULL"
        )
    )
    conn.execute(text("UPDATE tasks SET stage='done' WHERE done=1 AND stage!='done'"))
    conn.execute(
        text(
            "UPDATE tasks SET stage='backlog' "
            "WHERE done=0 AND (stage IS NULL OR stage='' OR stage='done')"
        )
    )

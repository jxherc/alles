"""m0073 - standing goals: the memory and limits behind a goal workflow."""

from sqlalchemy import text

VERSION = 73
NAME = "aide_goals"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS aide_goals ("
            "workflow_id VARCHAR PRIMARY KEY NOT NULL, notes TEXT DEFAULT '', "
            "status VARCHAR NOT NULL DEFAULT 'active', run_count INTEGER NOT NULL DEFAULT 0, "
            "max_runs INTEGER, until DATETIME, last_run_id VARCHAR, last_headline TEXT DEFAULT '', "
            "last_checked_at DATETIME, alerted_json TEXT DEFAULT '[]', created_at DATETIME, "
            "updated_at DATETIME, "
            "FOREIGN KEY(workflow_id) REFERENCES jarvis_workflows(id) ON DELETE CASCADE)"
        )
    )

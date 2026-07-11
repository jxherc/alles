"""m0018 - durable claims for safe legacy automation execution."""

from sqlalchemy import text

VERSION = 18
NAME = "automation_attempts"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS automation_attempts ("
            "id VARCHAR PRIMARY KEY NOT NULL, "
            "rule_id VARCHAR NOT NULL, "
            "occurrence_key VARCHAR(64) NOT NULL, "
            "status VARCHAR NOT NULL DEFAULT 'running', "
            "action VARCHAR NOT NULL DEFAULT '', "
            "error TEXT DEFAULT '', "
            "started_at DATETIME, "
            "finished_at DATETIME, "
            "FOREIGN KEY(rule_id) REFERENCES automation_rules(id) ON DELETE CASCADE"
            ")"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_automation_attempts_rule_occurrence "
            "ON automation_attempts(rule_id, occurrence_key)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_automation_attempts_rule_id "
            "ON automation_attempts(rule_id)"
        )
    )


def down(conn):
    conn.execute(text("DROP INDEX IF EXISTS ix_automation_attempts_rule_id"))
    conn.execute(text("DROP INDEX IF EXISTS ux_automation_attempts_rule_occurrence"))
    conn.execute(text("DROP TABLE IF EXISTS automation_attempts"))

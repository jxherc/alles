"""m0030 - add reviewed event inbox and legacy automation links."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 30
NAME = "jarvis_events_automation"


def up(conn):
    add_column(conn, "automation_rules", "migrated_workflow_id", "VARCHAR")
    add_column(conn, "automation_rules", "enabled_intent", "BOOLEAN")
    add_column(conn, "jarvis_workflows", "legacy_automation_id", "VARCHAR")
    add_column(conn, "jarvis_workflows", "review_state", "VARCHAR NOT NULL DEFAULT 'ready'")
    add_column(conn, "jarvis_workflows", "legacy_enabled_intent", "BOOLEAN DEFAULT 0")
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS jarvis_inbox_events ("
            "id VARCHAR PRIMARY KEY NOT NULL, source_kind VARCHAR NOT NULL, source_id VARCHAR DEFAULT '', "
            "event_type VARCHAR NOT NULL, entity_kind VARCHAR DEFAULT '', entity_id VARCHAR DEFAULT '', "
            "safe_summary TEXT DEFAULT '', external BOOLEAN DEFAULT 0, "
            "state VARCHAR NOT NULL DEFAULT 'pending', dedupe_key VARCHAR(64) NOT NULL UNIQUE, "
            "reviewed_at DATETIME, dispatched_at DATETIME, created_at DATETIME)"
        )
    )
    indexes = (
        "CREATE INDEX IF NOT EXISTS ix_automation_rules_migrated_workflow_id "
        "ON automation_rules(migrated_workflow_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jarvis_workflows_legacy_automation_id "
        "ON jarvis_workflows(legacy_automation_id)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_workflows_review_state "
        "ON jarvis_workflows(review_state)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_inbox_events_source_kind "
        "ON jarvis_inbox_events(source_kind)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_inbox_events_event_type "
        "ON jarvis_inbox_events(event_type)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_inbox_events_entity_kind "
        "ON jarvis_inbox_events(entity_kind)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_inbox_events_state "
        "ON jarvis_inbox_events(state)",
        "CREATE INDEX IF NOT EXISTS ix_jarvis_inbox_events_created_at "
        "ON jarvis_inbox_events(created_at)",
    )
    for statement in indexes:
        conn.execute(text(statement))

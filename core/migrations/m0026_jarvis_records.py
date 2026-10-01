"""m0026 - durable, separate Jarvis workflow and run records."""

from sqlalchemy import text

VERSION = 26
NAME = "jarvis_records"


_TABLES = (
    """CREATE TABLE IF NOT EXISTS jarvis_workflows (
        id VARCHAR PRIMARY KEY NOT NULL, name VARCHAR NOT NULL, purpose TEXT DEFAULT '',
        project_id VARCHAR, prompt TEXT DEFAULT '', deterministic_action VARCHAR DEFAULT '',
        model_override VARCHAR DEFAULT '', capability_ceiling TEXT DEFAULT '[]',
        concurrency_mode VARCHAR DEFAULT 'one', context_mode VARCHAR DEFAULT 'fresh',
        delivery_policy TEXT DEFAULT '{}', enabled BOOLEAN DEFAULT 0,
        created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL)""",
    """CREATE TABLE IF NOT EXISTS jarvis_triggers (
        id VARCHAR PRIMARY KEY NOT NULL, workflow_id VARCHAR NOT NULL, kind VARCHAR NOT NULL,
        config TEXT DEFAULT '{}', timezone VARCHAR DEFAULT 'UTC', enabled BOOLEAN DEFAULT 0,
        next_run_at DATETIME, last_run_at DATETIME, fingerprint VARCHAR DEFAULT '',
        created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(workflow_id) REFERENCES jarvis_workflows(id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS jarvis_runs (
        id VARCHAR PRIMARY KEY NOT NULL, workflow_id VARCHAR, trigger_id VARCHAR, project_id VARCHAR,
        session_id VARCHAR, state VARCHAR NOT NULL DEFAULT 'queued', scheduled_for DATETIME,
        occurrence_key VARCHAR(64), lease_owner VARCHAR DEFAULT '', lease_expires_at DATETIME,
        attempt_count INTEGER DEFAULT 0, failure_class VARCHAR DEFAULT '', safe_error TEXT DEFAULT '',
        result_summary TEXT DEFAULT '', left_project_root BOOLEAN DEFAULT 0,
        created_at DATETIME, started_at DATETIME, finished_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(workflow_id) REFERENCES jarvis_workflows(id) ON DELETE SET NULL,
        FOREIGN KEY(trigger_id) REFERENCES jarvis_triggers(id) ON DELETE SET NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE SET NULL)""",
    """CREATE TABLE IF NOT EXISTS jarvis_run_events (
        id VARCHAR PRIMARY KEY NOT NULL, run_id VARCHAR NOT NULL, sequence INTEGER NOT NULL,
        kind VARCHAR NOT NULL, source VARCHAR DEFAULT '', tool_name VARCHAR DEFAULT '',
        summary TEXT DEFAULT '', data TEXT DEFAULT '{}', created_at DATETIME,
        FOREIGN KEY(run_id) REFERENCES jarvis_runs(id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS jarvis_run_prompts (
        id VARCHAR PRIMARY KEY NOT NULL, run_id VARCHAR NOT NULL, kind VARCHAR NOT NULL,
        state VARCHAR NOT NULL DEFAULT 'pending', question TEXT NOT NULL, options TEXT DEFAULT '[]',
        action VARCHAR DEFAULT '', target TEXT DEFAULT '', data_summary TEXT DEFAULT '',
        privacy_effect TEXT DEFAULT '', cost VARCHAR DEFAULT '', capability VARCHAR DEFAULT '',
        expires_at DATETIME, answer TEXT DEFAULT '', responded_at DATETIME, used_at DATETIME,
        created_at DATETIME,
        FOREIGN KEY(run_id) REFERENCES jarvis_runs(id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS jarvis_delivery_attempts (
        id VARCHAR PRIMARY KEY NOT NULL, run_id VARCHAR NOT NULL, event_id VARCHAR,
        channel VARCHAR NOT NULL, privacy_level VARCHAR DEFAULT 'title_status',
        state VARCHAR NOT NULL DEFAULT 'pending', attempt_count INTEGER DEFAULT 0,
        next_attempt_at DATETIME, safe_error_class VARCHAR DEFAULT '',
        provider_message_id VARCHAR DEFAULT '', idempotency_key VARCHAR(64) NOT NULL UNIQUE,
        created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(run_id) REFERENCES jarvis_runs(id) ON DELETE CASCADE,
        FOREIGN KEY(event_id) REFERENCES jarvis_run_events(id) ON DELETE SET NULL)""",
    """CREATE TABLE IF NOT EXISTS jarvis_connectors (
        id VARCHAR PRIMARY KEY NOT NULL, name VARCHAR NOT NULL, kind VARCHAR NOT NULL,
        config TEXT DEFAULT '{}', secret TEXT DEFAULT '', allowlist TEXT DEFAULT '[]',
        enabled BOOLEAN DEFAULT 0, external BOOLEAN DEFAULT 1,
        created_at DATETIME, updated_at DATETIME)""",
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_triggers_workflow_id ON jarvis_triggers(workflow_id)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_triggers_next_run_at ON jarvis_triggers(next_run_at)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_runs_workflow_id ON jarvis_runs(workflow_id)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_runs_trigger_id ON jarvis_runs(trigger_id)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_runs_state ON jarvis_runs(state)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_runs_lease_expires_at ON jarvis_runs(lease_expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_run_events_run_id ON jarvis_run_events(run_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_jarvis_run_events_run_sequence "
    "ON jarvis_run_events(run_id,sequence)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_run_prompts_run_id ON jarvis_run_prompts(run_id)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_run_prompts_state ON jarvis_run_prompts(state)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_delivery_attempts_run_id "
    "ON jarvis_delivery_attempts(run_id)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_delivery_attempts_state "
    "ON jarvis_delivery_attempts(state)",
    "CREATE INDEX IF NOT EXISTS ix_jarvis_delivery_attempts_next_attempt_at "
    "ON jarvis_delivery_attempts(next_attempt_at)",
)


def up(conn):
    for statement in _TABLES:
        conn.execute(text(statement))
    for statement in _INDEXES:
        conn.execute(text(statement))

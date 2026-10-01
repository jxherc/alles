"""m0028 - add scoped grants and durable delegated actions."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 28
NAME = "delegated_actions"


_TABLES = (
    """CREATE TABLE IF NOT EXISTS capability_grants (
        id VARCHAR PRIMARY KEY NOT NULL, scope_kind VARCHAR NOT NULL, scope_id VARCHAR DEFAULT '',
        capability VARCHAR NOT NULL, target_root TEXT DEFAULT '', access_mode VARCHAR NOT NULL DEFAULT 'read',
        state VARCHAR NOT NULL DEFAULT 'active', expires_at DATETIME, last_used_at DATETIME,
        revoked_at DATETIME, created_at DATETIME, updated_at DATETIME)""",
    """CREATE TABLE IF NOT EXISTS delegated_actions (
        id VARCHAR PRIMARY KEY NOT NULL, origin VARCHAR NOT NULL, run_id VARCHAR, agent_run_id VARCHAR,
        session_id VARCHAR,
        grant_id VARCHAR, scope_kind VARCHAR NOT NULL, scope_id VARCHAR DEFAULT '',
        capability VARCHAR NOT NULL, action VARCHAR NOT NULL, target TEXT DEFAULT '',
        data_summary TEXT DEFAULT '', privacy_effect TEXT DEFAULT '', cost VARCHAR DEFAULT '',
        exact_hash VARCHAR(64) NOT NULL, pending_key VARCHAR(64), state VARCHAR NOT NULL DEFAULT 'pending',
        expires_at DATETIME NOT NULL, approved_at DATETIME, used_at DATETIME, finished_at DATETIME,
        created_at DATETIME, updated_at DATETIME,
        FOREIGN KEY(run_id) REFERENCES jarvis_runs(id) ON DELETE SET NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE SET NULL,
        FOREIGN KEY(grant_id) REFERENCES capability_grants(id) ON DELETE SET NULL)""",
    """CREATE TABLE IF NOT EXISTS capability_grant_events (
        id VARCHAR PRIMARY KEY NOT NULL, grant_id VARCHAR, action_id VARCHAR, kind VARCHAR NOT NULL,
        actor VARCHAR DEFAULT '', scope_kind VARCHAR DEFAULT '', scope_id VARCHAR DEFAULT '',
        capability VARCHAR DEFAULT '', created_at DATETIME,
        FOREIGN KEY(grant_id) REFERENCES capability_grants(id) ON DELETE SET NULL,
        FOREIGN KEY(action_id) REFERENCES delegated_actions(id) ON DELETE SET NULL)""",
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_capability_grants_scope_kind ON capability_grants(scope_kind)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grants_scope_id ON capability_grants(scope_id)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grants_capability ON capability_grants(capability)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grants_state ON capability_grants(state)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grants_expires_at ON capability_grants(expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_origin ON delegated_actions(origin)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_agent_run_id ON delegated_actions(agent_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_scope_kind ON delegated_actions(scope_kind)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_scope_id ON delegated_actions(scope_id)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_capability ON delegated_actions(capability)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_exact_hash ON delegated_actions(exact_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_delegated_actions_pending_key ON delegated_actions(pending_key)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_state ON delegated_actions(state)",
    "CREATE INDEX IF NOT EXISTS ix_delegated_actions_expires_at ON delegated_actions(expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grant_events_grant_id ON capability_grant_events(grant_id)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grant_events_action_id ON capability_grant_events(action_id)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grant_events_kind ON capability_grant_events(kind)",
    "CREATE INDEX IF NOT EXISTS ix_capability_grant_events_created_at ON capability_grant_events(created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_jarvis_run_prompts_delegated_action_id "
    "ON jarvis_run_prompts(delegated_action_id)",
)


def up(conn):
    add_column(conn, "jarvis_run_prompts", "delegated_action_id", "VARCHAR")
    for statement in _TABLES:
        conn.execute(text(statement))
    for statement in _INDEXES:
        conn.execute(text(statement))

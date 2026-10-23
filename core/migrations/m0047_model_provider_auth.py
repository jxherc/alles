"""m0047 - explicit model-provider authentication and Gemini OAuth state."""

from core.migrations.runner import add_column

VERSION = 47
NAME = "model_provider_auth"


def up(conn):
    for column, declaration in (
        ("provider_id", "TEXT NOT NULL DEFAULT ''"),
        ("auth_type", "TEXT NOT NULL DEFAULT 'api_key'"),
        ("auth_status", "TEXT NOT NULL DEFAULT 'incomplete'"),
        ("auth_error", "TEXT NOT NULL DEFAULT ''"),
        ("account_identity", "TEXT NOT NULL DEFAULT ''"),
        ("oauth_client_id", "TEXT NOT NULL DEFAULT ''"),
        ("oauth_client_secret", "TEXT NOT NULL DEFAULT ''"),
        ("oauth_project_id", "TEXT NOT NULL DEFAULT ''"),
        ("oauth_refresh_token", "TEXT NOT NULL DEFAULT ''"),
        ("oauth_expires_at", "REAL NOT NULL DEFAULT 0"),
        ("oauth_scopes", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        add_column(conn, "model_endpoints", column, declaration)

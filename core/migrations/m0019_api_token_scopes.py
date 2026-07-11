"""m0019 - explicit least-privilege scopes for API tokens."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 19
NAME = "api_token_scopes"


def up(conn):
    add_column(conn, "api_tokens", "scopes", "TEXT NOT NULL DEFAULT '[\"read\"]'")
    conn.execute(
        text(
            "UPDATE api_tokens SET scopes = '[\"read\"]' "
            "WHERE scopes IS NULL OR TRIM(scopes) = ''"
        )
    )

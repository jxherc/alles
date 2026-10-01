"""m0020 - explicit encrypted MCP environment and HTTP header fields."""

from core.migrations.runner import add_column

VERSION = 20
NAME = "mcp_credentials"


def up(conn):
    add_column(conn, "mcp_servers", "env", "TEXT NOT NULL DEFAULT '{}'")
    add_column(conn, "mcp_servers", "headers", "TEXT NOT NULL DEFAULT '{}'")

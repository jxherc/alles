"""m0022 - provider adapters, catalog state, and endpoint health."""

from core.migrations.runner import add_column

VERSION = 22
NAME = "model_catalogs"


def up(conn):
    add_column(conn, "model_endpoints", "provider_adapter", "TEXT NOT NULL DEFAULT 'auto'")
    add_column(conn, "model_endpoints", "catalog_status", "TEXT NOT NULL DEFAULT 'unverified'")
    add_column(conn, "model_endpoints", "catalog_source", "TEXT NOT NULL DEFAULT ''")
    add_column(conn, "model_endpoints", "catalog_error", "TEXT NOT NULL DEFAULT ''")
    add_column(conn, "model_endpoints", "catalog_refreshed_at", "DATETIME")
    add_column(conn, "model_endpoints", "unavailable_models", "TEXT NOT NULL DEFAULT '[]'")
    add_column(conn, "model_endpoints", "model_metadata", "TEXT NOT NULL DEFAULT '{}'")
    add_column(conn, "model_endpoints", "health_status", "TEXT NOT NULL DEFAULT 'unverified'")
    add_column(conn, "model_endpoints", "last_tested_at", "DATETIME")
    add_column(conn, "model_endpoints", "last_error_code", "TEXT NOT NULL DEFAULT ''")

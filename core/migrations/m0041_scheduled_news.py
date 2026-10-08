"""Durable first-class scheduled News sources, entries, configuration, and briefs."""

from sqlalchemy import text

VERSION = 41
NAME = "scheduled_news"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS news_configuration ("
            "id VARCHAR PRIMARY KEY, enabled BOOLEAN DEFAULT 0, "
            "cadence VARCHAR DEFAULT 'morning', time_of_day VARCHAR DEFAULT '08:00', "
            "timezone VARCHAR DEFAULT 'UTC', deliver_home BOOLEAN DEFAULT 1, "
            "deliver_jarvis BOOLEAN DEFAULT 0, next_run_at DATETIME, last_run_at DATETIME, "
            "last_success_at DATETIME, last_safe_error VARCHAR DEFAULT '', "
            "created_at DATETIME, updated_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS news_sources ("
            "id VARCHAR PRIMARY KEY, url VARCHAR NOT NULL UNIQUE, name VARCHAR DEFAULT '', "
            "category VARCHAR DEFAULT 'general', language VARCHAR DEFAULT 'en', "
            "priority INTEGER DEFAULT 1, schedule VARCHAR DEFAULT 'inherit', "
            "enabled BOOLEAN DEFAULT 1, etag VARCHAR DEFAULT '', last_modified VARCHAR DEFAULT '', "
            "last_checked_at DATETIME, last_success_at DATETIME, last_safe_error VARCHAR DEFAULT '', "
            "next_retry_at DATETIME, failure_count INTEGER DEFAULT 0, "
            "created_at DATETIME, updated_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS news_entries ("
            "id VARCHAR PRIMARY KEY, source_id VARCHAR NOT NULL REFERENCES news_sources(id) "
            "ON DELETE CASCADE, guid VARCHAR NOT NULL, canonical_url TEXT NOT NULL UNIQUE, "
            "title VARCHAR DEFAULT '', excerpt TEXT DEFAULT '', published_at DATETIME, "
            "content_hash VARCHAR(64) NOT NULL, cluster_key VARCHAR(64) DEFAULT '', "
            "fetched_at DATETIME, CONSTRAINT ux_news_entries_source_guid UNIQUE(source_id, guid))"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS news_briefs ("
            "id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL DEFAULT 'summary_pending', "
            "title VARCHAR DEFAULT 'news brief', summary TEXT DEFAULT '', clusters TEXT DEFAULT '[]', "
            "source_failures TEXT DEFAULT '[]', scheduled_for DATETIME, published_at DATETIME, "
            "delivered_home BOOLEAN DEFAULT 0, jarvis_delivery_state VARCHAR DEFAULT 'off', "
            "jarvis_attempt_count INTEGER DEFAULT 0, jarvis_next_attempt_at DATETIME, "
            "created_at DATETIME)"
        )
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_news_configuration_next_run ON news_configuration(next_run_at)",
        "CREATE INDEX IF NOT EXISTS ix_news_sources_next_retry ON news_sources(next_retry_at)",
        "CREATE INDEX IF NOT EXISTS ix_news_entries_source ON news_entries(source_id)",
        "CREATE INDEX IF NOT EXISTS ix_news_entries_published ON news_entries(published_at)",
        "CREATE INDEX IF NOT EXISTS ix_news_entries_hash ON news_entries(content_hash)",
        "CREATE INDEX IF NOT EXISTS ix_news_entries_cluster ON news_entries(cluster_key)",
        "CREATE INDEX IF NOT EXISTS ix_news_briefs_status ON news_briefs(status)",
        "CREATE INDEX IF NOT EXISTS ix_news_briefs_published ON news_briefs(published_at)",
        "CREATE INDEX IF NOT EXISTS ix_news_briefs_jarvis ON news_briefs(jarvis_delivery_state)",
        "CREATE INDEX IF NOT EXISTS ix_news_briefs_jarvis_retry ON news_briefs(jarvis_next_attempt_at)",
    ):
        conn.execute(text(statement))

"""m0045 - durable Andromeda background verification jobs."""

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 45
NAME = "andromeda_verification_jobs"


def up(conn):
    add_column(
        conn,
        "andromeda_saved_searches",
        "verification_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    add_column(
        conn,
        "andromeda_saved_searches",
        "verifier_model_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS andromeda_verification_jobs ("
            "id VARCHAR PRIMARY KEY, query TEXT NOT NULL, "
            "answer_json TEXT NOT NULL DEFAULT '{}', results_json TEXT NOT NULL DEFAULT '[]', "
            "evidence_json TEXT NOT NULL DEFAULT '[]', model_json TEXT NOT NULL DEFAULT '{}', "
            "result_json TEXT NOT NULL DEFAULT '{}', status VARCHAR NOT NULL DEFAULT 'pending', "
            "error_code VARCHAR NOT NULL DEFAULT '', checked_at DATETIME, "
            "created_at DATETIME, updated_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_andromeda_verification_jobs_status "
            "ON andromeda_verification_jobs(status)"
        )
    )

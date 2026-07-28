"""m0038 - additive Actual staging, entity links, and reversible ledger authority."""

from sqlalchemy import text

VERSION = 38
NAME = "actual_cutover_state"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS finance_ledger_state ("
            "id VARCHAR NOT NULL PRIMARY KEY, mode VARCHAR NOT NULL DEFAULT 'alles', "
            "base_currency_code VARCHAR NOT NULL DEFAULT 'CAD', active_run_id VARCHAR NOT NULL DEFAULT '', "
            "actual_budget_id VARCHAR NOT NULL DEFAULT '', actual_sync_id VARCHAR NOT NULL DEFAULT '', "
            "legacy_read_only BOOLEAN NOT NULL DEFAULT 0, cutover_at DATETIME, rollback_at DATETIME, "
            "updated_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "INSERT OR IGNORE INTO finance_ledger_state "
            "(id,mode,base_currency_code,active_run_id,actual_budget_id,actual_sync_id,legacy_read_only) "
            "VALUES ('primary','alles','CAD','','','',0)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS actual_migration_runs ("
            "id VARCHAR NOT NULL PRIMARY KEY, status VARCHAR NOT NULL DEFAULT 'staging', "
            "base_currency_code VARCHAR NOT NULL, snapshot_sha256 VARCHAR NOT NULL, "
            "snapshot_path TEXT NOT NULL, actual_budget_id VARCHAR NOT NULL DEFAULT '', "
            "actual_sync_id VARCHAR NOT NULL DEFAULT '', report_json TEXT NOT NULL DEFAULT '{}', "
            "error TEXT NOT NULL DEFAULT '', created_at DATETIME, verified_at DATETIME, "
            "cutover_at DATETIME, rolled_back_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS actual_entity_links ("
            "id VARCHAR NOT NULL PRIMARY KEY, run_id VARCHAR NOT NULL, entity_kind VARCHAR NOT NULL, "
            "source_id VARCHAR NOT NULL, actual_id VARCHAR NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', "
            "created_at DATETIME, CONSTRAINT uq_actual_link_source UNIQUE(run_id,entity_kind,source_id))"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_actual_entity_links_run_id ON actual_entity_links(run_id)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_actual_entity_links_entity_kind ON actual_entity_links(entity_kind)"
        )
    )

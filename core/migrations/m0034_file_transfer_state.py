"""m0034 - durable offline cache identity for Phase 7 Files transfers."""

from sqlalchemy import text

VERSION = 34
NAME = "file_transfer_state"


def up(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS offline_files ("
            "id VARCHAR PRIMARY KEY, location_id VARCHAR NOT NULL, "
            "normalized_path VARCHAR NOT NULL, state VARCHAR NOT NULL DEFAULT 'queued', "
            "cache_name VARCHAR DEFAULT '', size INTEGER DEFAULT 0, checksum VARCHAR DEFAULT '', "
            "etag VARCHAR DEFAULT '', version_id VARCHAR DEFAULT '', error_code VARCHAR DEFAULT '', "
            "created_at DATETIME, updated_at DATETIME, "
            "CONSTRAINT uq_offline_files_location_path UNIQUE (location_id, normalized_path), "
            "FOREIGN KEY(location_id) REFERENCES storage_locations(id) ON DELETE RESTRICT)"
        )
    )
    for name, column in {
        "ix_offline_files_location_id": "location_id",
        "ix_offline_files_normalized_path": "normalized_path",
        "ix_offline_files_state": "state",
    }.items():
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON offline_files("{column}")'))

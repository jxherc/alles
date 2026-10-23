"""Ordered schema and credential initialization for every startup path."""

import os

from core.database_credentials import encrypt_plaintext_secrets
from core.schema import Base


def initialize_database(engine, db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    Base.metadata.create_all(engine)
    from core.build_info import SQLITE_APPLICATION_ID

    with engine.begin() as conn:
        conn.exec_driver_sql(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
    # schema migrations (versioned runner; baseline self-heals every boot)
    from core.migrations import run_migrations

    run_migrations(engine)
    encrypt_plaintext_secrets(engine)
    from core.settings import migrate_setting_secrets

    migrate_setting_secrets()
    from services.caldav_sync import migrate_cfg_secrets as migrate_caldav_secrets
    from services.carddav_sync import migrate_cfg_secrets as migrate_carddav_secrets
    from services.s3_backup import migrate_config as migrate_s3_secrets
    from services.webdav_backup import migrate_config as migrate_webdav_secrets

    migrate_caldav_secrets()
    migrate_carddav_secrets()
    migrate_s3_secrets()
    migrate_webdav_secrets()

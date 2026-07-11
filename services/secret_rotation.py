"""Crash-safe rotation for every server-side credential encrypted by Alles."""

import json
from pathlib import Path

from sqlalchemy import text


def _cipher_references() -> tuple[set[str], bool]:
    from core.database import _SECRET_COLUMNS, engine
    from core.settings import _SETTINGS_FILE
    from services.caldav_sync import _cfg_path as caldav_path
    from services.carddav_sync import _cfg_path as carddav_path
    from services.secretstore import LEGACY_PREFIX, cipher_key_id

    values: list[str] = []
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        for table, column, _purpose in _SECRET_COLUMNS:
            if table not in tables:
                continue
            columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            if column in columns:
                values.extend(
                    row[0]
                    for row in connection.execute(
                        text(f"SELECT {column} FROM {table} WHERE {column} != ''")
                    )
                    if isinstance(row[0], str)
                )

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            values.append(value)

    for path in (_SETTINGS_FILE, caldav_path(), carddav_path()):
        try:
            walk(json.loads(Path(path).read_text("utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            continue

    ids = {key_id for value in values if (key_id := cipher_key_id(value))}
    legacy = any(value.startswith(LEGACY_PREFIX) for value in values)
    return ids, legacy


def rotate_all_credentials() -> dict:
    """Retain the old key until every known credential has been rewritten."""
    from core.database import _encrypt_plaintext_secrets
    from core.settings import migrate_setting_secrets
    from services.caldav_sync import migrate_cfg_secrets as migrate_caldav
    from services.carddav_sync import migrate_cfg_secrets as migrate_carddav
    from services.secretstore import key_ids, prune_keys, rotate_key

    old_ids = key_ids()
    active = rotate_key()
    changed = _encrypt_plaintext_secrets(force_reseal=True)
    changed += migrate_setting_secrets()
    changed += migrate_caldav()
    changed += migrate_carddav()
    references, legacy = _cipher_references()
    prune_keys(key_ids() if legacy else references)
    return {
        "ok": True,
        "changed": changed,
        "active_key": active,
        "retired_keys": len(old_ids - key_ids()),
    }

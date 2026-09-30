"""Credential flush locks and migrations for the machine-local keyring."""

from sqlalchemy import text

from core.credential_inventory import DATABASE_CREDENTIAL_FIELDS

_SECRET_COLUMNS = DATABASE_CREDENTIAL_FIELDS

_CREDENTIAL_TABLES = frozenset(table for table, _column, _purpose in _SECRET_COLUMNS)
_CREDENTIAL_LOCK_INFO = "alles_credential_write_lock"


def _lock_credential_session(session, _flush_context, _instances):
    if session.info.get(_CREDENTIAL_LOCK_INFO):
        return
    changed = (*session.new, *session.dirty, *session.deleted)
    if not any(getattr(item, "__tablename__", "") in _CREDENTIAL_TABLES for item in changed):
        return
    from services.recovery_consistency import recovery_consistency_lock

    recovery_consistency_lock.acquire()
    session.info[_CREDENTIAL_LOCK_INFO] = recovery_consistency_lock


def _unlock_credential_session(session, transaction):
    if transaction.parent is not None:
        return
    lock = session.info.pop(_CREDENTIAL_LOCK_INFO, None)
    if lock is not None:
        lock.release()


def encrypt_plaintext_secrets(engine, force_reseal: bool = False) -> int:
    """Seal legacy connector fields and move old ciphertext onto the active key."""
    from services.secretstore import needs_reseal, reseal

    changed = 0
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).fetchall()
        }
        for table, col, purpose in _SECRET_COLUMNS:
            if table not in tables:
                continue
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if col not in columns:
                continue
            rows = conn.execute(text(f"SELECT id, {col} FROM {table} WHERE {col} != ''")).fetchall()
            for rid, val in rows:
                if not force_reseal and not needs_reseal(val):
                    continue
                conn.execute(
                    text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                    {"v": reseal(val, purpose), "id": rid},
                )
                changed += 1
    return changed

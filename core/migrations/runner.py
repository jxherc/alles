"""tiny versioned migration runner.

each migration module (m0001_baseline.py, m0002_*.py, ...) declares:
  VERSION: int            unique, applied in ascending order
  NAME: str
  up(conn)                apply it
  down(conn)              optional, revert it
  ALWAYS = True           optional - re-run up() every boot (idempotent self-heal); only the
                          baseline uses this, so a dropped base column still gets re-added.

versions are recorded in `schema_migrations`. run_migrations returns the versions NEWLY applied
(an ALWAYS migration runs every time but is only recorded/returned the first time). unlike the
old `_add_col`, errors from a migration's up() are NOT swallowed - they propagate and the
version is not recorded.
"""

import importlib
import pkgutil
from datetime import datetime

from sqlalchemy import text


def _ensure_table(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
        )
    )


def applied_versions(conn) -> set:
    _ensure_table(conn)
    conn.commit()  # persist the DDL so a separate connection sees the table
    return {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}


def add_column(conn, table, col, coltype) -> bool:
    """idempotent column add. returns True if added, False if it already existed. RAISES on a
    real error (bad table/type) - the whole point vs the old silent `_add_col`."""
    have = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
    if col in have:
        return False
    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {coltype}'))
    return True


def discover(package="core.migrations") -> list:
    pkg = importlib.import_module(package)
    mods = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.name.startswith("m"):
            continue
        m = importlib.import_module(f"{package}.{info.name}")
        if hasattr(m, "VERSION") and hasattr(m, "up"):
            mods.append(m)
    mods.sort(key=lambda m: m.VERSION)
    return mods


def run_migrations(engine, *, modules=None) -> list:
    mods = list(modules) if modules is not None else discover()
    mods.sort(key=lambda m: m.VERSION)
    with engine.connect() as conn:
        done = applied_versions(conn)
    newly = []
    for m in mods:
        always = getattr(m, "ALWAYS", False)
        first_time = m.VERSION not in done
        if not first_time and not always:
            continue
        with engine.begin() as conn:
            m.up(conn)
            if first_time:
                conn.execute(
                    text(
                        "INSERT INTO schema_migrations(version,name,applied_at) VALUES (:v,:n,:t)"
                    ),
                    {"v": m.VERSION, "n": m.NAME, "t": datetime.utcnow().isoformat()},
                )
                newly.append(m.VERSION)
    return newly

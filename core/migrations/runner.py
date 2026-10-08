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
from datetime import UTC, datetime

from sqlalchemy import text


class MigrationHistoryError(RuntimeError):
    """The database claims a migration history this release cannot safely trust."""


class MigrationBlockedError(RuntimeError):
    """A migration could not prove that its safety condition completed."""


PHOTO_FORK_NAMES = {
    9: "photo_archive",
    10: "photo_perf",
    11: "photo_stack",
    12: "photo_clip",
    13: "photo_faces",
}
PHOTO_FORK_TARGETS = {version: version + 3 for version in PHOTO_FORK_NAMES}
PHOTO_FORK_COLUMNS = {
    9: {"archived"},
    10: {"aspect_ratio", "preview", "checksum"},
    11: {"stack_id"},
    12: {"clip"},
    13: {"faces_at"},
}


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


def migration_catalog(modules=None) -> dict[int, str]:
    mods = list(modules) if modules is not None else discover()
    catalog = {}
    for module in mods:
        version = getattr(module, "VERSION", None)
        name = getattr(module, "NAME", None)
        if not isinstance(version, int) or version < 1 or not isinstance(name, str) or not name:
            raise MigrationHistoryError("invalid migration module metadata")
        if version in catalog:
            raise MigrationHistoryError(f"duplicate migration version: {version}")
        catalog[version] = name
    return catalog


def _record_pair(record) -> tuple[int, str]:
    if isinstance(record, dict):
        version, name = record.get("version"), record.get("name")
    else:
        try:
            version, name = record[0], record[1]
        except (IndexError, KeyError, TypeError) as exc:
            raise MigrationHistoryError("invalid migration history record") from exc
    if not isinstance(version, int) or version < 1 or not isinstance(name, str) or not name:
        raise MigrationHistoryError("invalid migration history record")
    return version, name


def validate_migration_history(records, *, modules=None, allow_known_photo_fork=True) -> dict:
    """Validate names and identify the one historical Photos migration fork we shipped."""
    catalog = migration_catalog(modules)
    history = {}
    for record in records:
        version, name = _record_pair(record)
        if version in history:
            raise MigrationHistoryError(f"duplicate migration history version: {version}")
        history[version] = name

    fork_versions = []
    if allow_known_photo_fork and history.get(9) == PHOTO_FORK_NAMES[9]:
        version = 9
        while version in PHOTO_FORK_NAMES and history.get(version) == PHOTO_FORK_NAMES[version]:
            fork_versions.append(version)
            version += 1

    fork_set = set(fork_versions)
    for version, name in history.items():
        if version in fork_set:
            continue
        expected = catalog.get(version)
        if expected is None:
            raise MigrationHistoryError(
                "database uses a newer or unknown migration than this Alles release"
            )
        if name != expected:
            raise MigrationHistoryError(f"migration {version} does not match this Alles release")

    return {
        "kind": "photo-fork" if fork_versions else "canonical",
        "fork_versions": tuple(fork_versions),
        "history": history,
        "catalog": catalog,
    }


def _history_rows(conn) -> list[tuple[int, str, str]]:
    return [
        (row[0], row[1], row[2])
        for row in conn.execute(
            text("SELECT version, name, applied_at FROM schema_migrations ORDER BY version")
        )
    ]


def _verify_photo_fork_shape(conn, fork_versions: tuple[int, ...]) -> None:
    tables = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "photos" not in tables:
        raise MigrationHistoryError("Photos migration history exists without a photos table")
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(photos)"))}
    for version in fork_versions:
        missing = PHOTO_FORK_COLUMNS[version] - columns
        if missing:
            joined = ", ".join(sorted(missing))
            raise MigrationHistoryError(
                f"Photos migration {version} is missing expected columns: {joined}"
            )


def reconcile_known_migration_history(conn, *, modules=None) -> dict:
    """Rewrite the exact historical Photos fork into canonical version numbers.

    It also rewinds the old false-success Notes drop marker when the legacy table still exists.
    Both repairs are safe to re-run and happen before normal migrations.
    """
    _ensure_table(conn)
    rows = _history_rows(conn)
    checked = validate_migration_history(rows, modules=modules, allow_known_photo_fork=True)
    catalog = checked["catalog"]
    fork_versions = checked["fork_versions"]

    if fork_versions:
        _verify_photo_fork_shape(conn, fork_versions)
        old_rows = {version: (name, applied_at) for version, name, applied_at in rows}
        for version in fork_versions:
            conn.execute(
                text("DELETE FROM schema_migrations WHERE version = :version"),
                {"version": version},
            )

        current = {version: name for version, name, _ in _history_rows(conn)}
        for old_version in fork_versions:
            target = PHOTO_FORK_TARGETS[old_version]
            expected = catalog.get(target)
            if expected is None:
                raise MigrationHistoryError("this release cannot map the Photos migration fork")
            if target in current:
                if current[target] != expected:
                    raise MigrationHistoryError(
                        f"cannot reconcile Photos migration into version {target}"
                    )
                continue
            _, applied_at = old_rows[old_version]
            conn.execute(
                text(
                    "INSERT INTO schema_migrations(version,name,applied_at) "
                    "VALUES (:version,:name,:applied_at)"
                ),
                {"version": target, "name": expected, "applied_at": applied_at},
            )
            current[target] = expected

    tables = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    current = {version: name for version, name, _ in _history_rows(conn)}
    if (
        "notes" in tables
        and catalog.get(9) == "notes_to_vault"
        and catalog.get(10) == "drop_note_table"
        and current.get(10) == catalog[10]
    ):
        # Older m0010 returned success when files were missing. Re-run both Notes steps so the
        # Markdown copy is verified before the table can be dropped.
        conn.execute(
            text(
                "DELETE FROM schema_migrations "
                "WHERE (version = 9 AND name = :m9) OR (version = 10 AND name = :m10)"
            ),
            {"m9": catalog[9], "m10": catalog[10]},
        )

    final_rows = _history_rows(conn)
    return validate_migration_history(
        final_rows,
        modules=modules,
        allow_known_photo_fork=False,
    )


def run_migrations(engine, *, modules=None) -> list:
    production_history = modules is None
    mods = list(modules) if modules is not None else discover()
    mods.sort(key=lambda m: m.VERSION)
    migration_catalog(mods)
    if production_history:
        with engine.begin() as conn:
            reconcile_known_migration_history(conn, modules=mods)
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
                    {
                        "v": m.VERSION,
                        "n": m.NAME,
                        "t": datetime.now(UTC).replace(tzinfo=None).isoformat(),
                    },
                )
                newly.append(m.VERSION)
    return newly

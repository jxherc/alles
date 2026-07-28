"""Small, public build markers used by recovery and diagnostics."""

import os

RECOVERY_COMPATIBILITY = 1
SQLITE_APPLICATION_ID = 0x414C4C53  # ASCII: ALLS

# Shipped Afterlife surfaces are the clean-install default. Keep unfinished surfaces explicit
# and off: an environment typo must never invent and enable a new feature.
AFTERLIFE_FEATURE_DEFAULTS = {
    "afterlife_shell": True,
    "afterlife_today": True,
    "afterlife_aide_projects": True,
    "afterlife_andromeda": True,
    "afterlife_jarvis": False,
    "afterlife_storage_locations": False,
}
AFTERLIFE_FEATURES_ENV = "ALLES_AFTERLIFE_FEATURES"


def build_info() -> dict[str, str | int]:
    return {
        "name": "alles",
        "version": os.environ.get("ALLES_VERSION", "development"),
        "build_id": os.environ.get("ALLES_BUILD_ID", "local"),
        "recovery_compatibility": RECOVERY_COMPATIBILITY,
    }


def migration_head() -> int:
    """Return the newest schema version understood by this release."""
    from core.migrations.runner import migration_catalog

    return max(migration_catalog(), default=0)


def afterlife_feature_flags(raw: str | None = None) -> dict[str, bool]:
    """Return the fixed Afterlife flag set, with an optional strict env allow-list.

    With no override, shipped surfaces use their clean-install defaults. A non-empty
    ``ALLES_AFTERLIFE_FEATURES`` value is a strict comma-separated allow-list, which lets tests
    and development runs isolate one surface. Unknown, blank, or duplicate entries are rejected
    instead of being guessed.
    """
    flags = dict(AFTERLIFE_FEATURE_DEFAULTS)
    value = os.environ.get(AFTERLIFE_FEATURES_ENV, "") if raw is None else raw
    if not value.strip():
        return flags

    requested = [item.strip() for item in value.split(",")]
    if any(not item for item in requested):
        raise ValueError(f"{AFTERLIFE_FEATURES_ENV} contains a blank feature name")
    if len(requested) != len(set(requested)):
        raise ValueError(f"{AFTERLIFE_FEATURES_ENV} contains a duplicate feature name")

    unknown = sorted(set(requested) - flags.keys())
    if unknown:
        raise ValueError(f"unknown {AFTERLIFE_FEATURES_ENV} value(s): {', '.join(unknown)}")
    flags = {name: False for name in flags}
    for name in requested:
        flags[name] = True
    return flags


def runtime_info() -> dict:
    """Public, secret-free metadata used by the running app."""
    return {
        **build_info(),
        "migration_head": migration_head(),
        "feature_flags": afterlife_feature_flags(),
    }

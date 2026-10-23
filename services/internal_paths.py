"""Short, filesystem-safe names for private staging artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _component_limit(directory: Path) -> int:
    try:
        return int(os.pathconf(directory, "PC_NAME_MAX"))
    except (AttributeError, OSError, TypeError, ValueError):
        return 255


def _truncate_utf8(value: str, maximum: int) -> str:
    if maximum <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", errors="ignore")


def _clean(value: str) -> str:
    return "".join(
        character for character in str(value) if character.isalnum() or character in "-_"
    )


def artifact_sibling(
    target: Path,
    label: str,
    *,
    identity: str = "",
    suffix: str = "",
) -> Path:
    """Return one stable private sibling without extending the user filename."""
    target = Path(target)
    clean_label = _clean(label)[:32] or "artifact"
    digest = hashlib.sha256(
        f"{target.name}\0{identity}".encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:32]
    name = f".alles-{clean_label}-{digest}{suffix}"
    if len(name.encode("utf-8")) > _component_limit(target.parent):
        raise OSError("private staging filename exceeds the filesystem limit")
    return target.with_name(name)


def operation_sibling(target: Path, operation_id: str, suffix: str) -> Path:
    """Return a stable private sibling owned by one Files operation."""
    target = Path(target)
    clean_id = _clean(operation_id)
    if not clean_id:
        raise ValueError("operation identity is invalid")
    name = f".alles-{clean_id}{suffix}"
    if len(name.encode("utf-8")) > _component_limit(target.parent):
        clean_id = hashlib.sha256(clean_id.encode("utf-8")).hexdigest()
        name = f".alles-{clean_id}{suffix}"
    if len(name.encode("utf-8")) > _component_limit(target.parent):
        raise OSError("private operation filename exceeds the filesystem limit")
    return target.with_name(name)


def bounded_named_child(parent: Path, desired_name: str, *, prefix: str = "") -> Path:
    """Keep a useful display name while respecting the directory component limit."""
    parent = Path(parent)
    raw_name = Path(desired_name).name or "file"
    clean_prefix = _clean(prefix)
    prefix_text = f"{clean_prefix}-" if clean_prefix else ""
    available = _component_limit(parent) - len(prefix_text.encode("utf-8"))
    if available <= 0:
        raise OSError("private filename prefix exceeds the filesystem limit")
    suffix = Path(raw_name).suffix
    if len(suffix.encode("utf-8")) >= available:
        suffix = ""
    stem = raw_name[: -len(suffix)] if suffix else raw_name
    stem = _truncate_utf8(stem, available - len(suffix.encode("utf-8"))) or "file"
    name = f"{prefix_text}{stem}{suffix}"
    if len(name.encode("utf-8")) > _component_limit(parent):
        name = _truncate_utf8(name, _component_limit(parent))
    return parent / name

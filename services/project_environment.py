"""Folder-backed Project and General environment helpers."""

from pathlib import Path


def canonical_folder(value: str, *, must_exist: bool = False) -> str:
    """Return a canonical absolute folder path or raise a stable ValueError."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("project_folder_must_be_absolute")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise ValueError("project_folder_unavailable") from exc
    if must_exist and not resolved.is_dir():
        raise ValueError("project_folder_unavailable")
    if resolved == Path(resolved.anchor):
        raise ValueError("project_folder_is_filesystem_root")
    return str(resolved)


def folder_state(value: str) -> str:
    """Describe a saved Project path without changing it."""
    raw = str(value or "").strip()
    if not raw:
        return "relink_required"
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            return "relink_required"
        resolved = path.resolve(strict=True)
        if resolved == Path(resolved.anchor):
            return "relink_required"
        return "available" if resolved.is_dir() else "missing"
    except (OSError, RuntimeError):
        return "missing"


def session_environment(session) -> dict:
    """Resolve one session without treating General as the Alles source tree."""
    project = getattr(session, "project", None)
    if project is not None:
        state = folder_state(getattr(project, "working_dir", ""))
        cwd = ""
        if state == "available":
            cwd = canonical_folder(project.working_dir, must_exist=True)
        return {
            "kind": "project",
            "project_id": project.id,
            "cwd": cwd,
            "folder_state": state,
        }

    dangling_project_id = getattr(session, "project_id", None)
    if dangling_project_id:
        return {
            "kind": "project",
            "project_id": dangling_project_id,
            "cwd": "",
            "folder_state": "relink_required",
        }

    legacy = str(getattr(session, "working_dir", "") or "").strip()
    if legacy:
        try:
            cwd = canonical_folder(legacy, must_exist=True)
        except ValueError:
            return {
                "kind": "legacy_folder",
                "project_id": None,
                "cwd": "",
                "folder_state": "relink_required",
            }
        return {
            "kind": "legacy_folder",
            "project_id": None,
            "cwd": cwd,
            "folder_state": "available",
        }

    return {
        "kind": "general",
        "project_id": None,
        "cwd": "",
        "folder_state": "none",
    }

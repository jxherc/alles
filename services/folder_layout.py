"""One visible folder for a native install: ~/Alles is the files root, docs sit in ~/Alles/Docs,
and automatic backups live in the hidden alles folder next to the data.

owner, oct 27: "all the files should be in one universal location ... so i can open and see them
in the files". installs before nov 1 used ~/Alles/Vault, ~/Alles/Files and ~/Alles/Backups.

the move is renames only, on one disk, so no byte is copied and nothing is deleted. it writes a
journal before the first rename; every step is idempotent, so a process that dies anywhere is
finished by the next run (or put back when a step can't finish). folders on another disk, custom
folders or a name clash leave the layout as it is and say why.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

JOURNAL = "folder-move.json"
_DROPPABLE = {".DS_Store"}  # finder metadata; a second copy in the target is dropped, not moved
_PATH_KEYS = ("vault_dir", "files_dir", "automatic_backup_dir")
_DEFAULT_LOCATION = "default-local"


class FolderMoveError(RuntimeError):
    pass


def visible_root(home: Path) -> Path:
    return home / "Alles"


def backups_dir(support_root: Path) -> Path:
    return support_root / "backups"


def _targets(layout) -> dict:
    root = visible_root(layout.home)
    return {"root": root, "docs": root / "Docs", "backups": backups_dir(layout.support_root)}


def _legacy(layout) -> dict:
    root = visible_root(layout.home)
    return {"vault": root / "Vault", "files": root / "Files", "backups": root / "Backups"}


def journal_path(layout) -> Path:
    return layout.support_root / JOURNAL


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: dict, mode: int = 0o600) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    _fsync_dir(path.parent)


def _read_settings(data_root: Path) -> dict:
    path = data_root / "settings.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FolderMoveError("settings.json can't be read") from exc
    if not isinstance(value, dict):
        raise FolderMoveError("settings.json must hold an object")
    return value


def _resolved(value) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else None


def _remap(value: str, moves: list[tuple[Path, Path]]) -> str | None:
    """The same path after the move, or None when the move doesn't touch it."""
    path = _resolved(value)
    if path is None:
        return None
    for old, new in moves:
        if path == old:
            return str(new)
        if old in path.parents:
            return str(new / path.relative_to(old))
    return None


def _inventory(base: Path, names: list[str]) -> dict:
    """Count, bytes and a digest of every entry under base/<name>, by its path from base."""
    entries = []
    for name in names:
        top = base / name
        if top.is_symlink() or not top.is_dir():
            st = top.lstat()
            entries.append(f"{name}\0{st.st_size if top.is_file() else -1}")
            continue
        entries.append(f"{name}/\0-1")
        for current, dirs, files in os.walk(top, followlinks=False):
            rel = Path(current).relative_to(base).as_posix()
            for child in dirs:
                entries.append(f"{rel}/{child}/\0-1")
            for child in files:
                path = Path(current) / child
                st = path.lstat()
                size = st.st_size if not path.is_symlink() else -1
                entries.append(f"{rel}/{child}\0{size}")
    entries.sort()
    digest = hashlib.sha256("\n".join(entries).encode("utf-8", "surrogatepass")).hexdigest()
    total = 0
    for item in entries:
        size = int(item.rsplit("\0", 1)[1])
        total += max(size, 0)
    return {"count": len(entries), "bytes": total, "sha256": digest}


def _tree(path: Path) -> dict:
    """The inventory of one folder by paths inside it, so a renamed folder compares equal."""
    return _inventory(path, sorted(os.listdir(path)))


def _same_disk(paths: list[Path]) -> bool:
    devices = set()
    for path in paths:
        probe = path
        while not probe.exists():
            probe = probe.parent
        devices.add(probe.stat().st_dev)
    return len(devices) == 1


def plan(layout) -> dict:
    """Where the folders are and what a move would do. Never changes anything.

    state: "one-folder" (done), "move" (ready), "kept" (left as is, with why), "unfinished"
    (a journal waits), or "inside-data" (setup never put the folders in view).
    """
    journal = journal_path(layout)
    if journal.exists():
        record = _load_journal(journal)
        if record.get("state") not in {"done", "rolled_back"}:
            return {"state": "unfinished", "why": "a folder move stopped half way"}
    targets, legacy = _targets(layout), _legacy(layout)
    settings = _read_settings(layout.data_root)
    vault = _resolved(settings.get("vault_dir"))
    files = _resolved(settings.get("files_dir"))
    root = targets["root"].resolve() if targets["root"].exists() else targets["root"]
    if files == root and vault is not None and root in vault.parents:
        return {"state": "one-folder", "root": str(targets["root"])}
    if vault is None and files is None:
        return {"state": "inside-data", "why": "docs and files are still inside the data folder"}
    if vault != legacy["vault"].resolve() or files != legacy["files"].resolve():
        return {"state": "kept", "why": "your docs and files folders are your own choice"}
    for path in (legacy["vault"], legacy["files"]):
        if path.is_symlink() or not path.is_dir():
            return {"state": "kept", "why": f"{path} is missing or a link"}
    if targets["root"].is_symlink():
        return {"state": "kept", "why": f"{targets['root']} is a link"}

    move_backups = _resolved(settings.get("automatic_backup_dir")) in (
        None,
        legacy["backups"].resolve(),
    )
    backups_folder = move_backups and legacy["backups"].is_dir()
    if backups_folder and legacy["backups"].is_symlink():
        return {"state": "kept", "why": f"{legacy['backups']} is a link"}
    if backups_folder and targets["backups"].exists():
        return {"state": "kept", "why": f"{targets['backups']} already exists"}
    if targets["docs"].exists() or targets["docs"].is_symlink():
        return {"state": "kept", "why": f"{targets['docs']} already exists"}

    children = sorted(os.listdir(legacy["files"]))
    disk = [targets["root"], legacy["vault"], legacy["files"]]
    disk += [legacy["files"] / name for name in children]
    if backups_folder:
        disk += [legacy["backups"], layout.support_root]
    if not _same_disk(disk):
        return {"state": "kept", "why": "the folders sit on more than one disk"}

    taken = set(os.listdir(targets["root"])) - {legacy["vault"].name}
    if backups_folder:
        taken.discard(legacy["backups"].name)
    taken.add(targets["docs"].name)
    clashes, drop = [], []
    for name in children:
        if name in taken:
            if name in _DROPPABLE:
                drop.append(name)
            else:
                clashes.append(name)
    if clashes:
        shown = ", ".join(clashes[:3]) + (" ..." if len(clashes) > 3 else "")
        return {"state": "kept", "why": f"~/Alles already has {shown}"}

    renames = []
    if backups_folder:
        renames.append({"src": str(legacy["backups"]), "dst": str(targets["backups"])})
    renames.append({"src": str(legacy["vault"]), "dst": str(targets["docs"])})
    for name in children:
        if name not in drop:
            renames.append({"src": str(legacy["files"] / name), "dst": str(targets["root"] / name)})
    path_moves = [
        (legacy["vault"].resolve(), targets["docs"]),
        (legacy["files"].resolve(), targets["root"]),
    ]
    if move_backups:
        path_moves.append((legacy["backups"].resolve(), targets["backups"]))
    settings_old, settings_new = {}, {}
    for key, value in settings.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            moved = _remap(value, path_moves)
            if moved is not None:
                settings_old[key], settings_new[key] = value, moved
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            moved_list = [_remap(item, path_moves) or item for item in value]
            if moved_list != value:
                settings_old[key], settings_new[key] = value, moved_list
    if move_backups and "automatic_backup_dir" not in settings_new:
        settings_old["automatic_backup_dir"] = settings.get("automatic_backup_dir")
        settings_new["automatic_backup_dir"] = str(targets["backups"])
    return {
        "state": "move",
        "renames": renames,
        "drop": [str(legacy["files"] / name) for name in drop],
        "empty": str(legacy["files"]),
        "settings_old": settings_old,
        "settings_new": settings_new,
        "path_moves": [[str(old), str(new)] for old, new in path_moves],
        "inventory": {
            "files": _inventory(legacy["files"], [n for n in children if n not in drop]),
            "docs": _tree(legacy["vault"]),
            "backups": _tree(legacy["backups"]) if backups_folder else None,
        },
        "children": [n for n in children if n not in drop],
    }


def _load_journal(path: Path) -> dict:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FolderMoveError(f"the folder move journal can't be read: {path}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise FolderMoveError(f"the folder move journal is not one alles wrote: {path}")
    return value


def _save(path: Path, journal: dict) -> None:
    _atomic_json(path, journal)


def _rename(src: Path, dst: Path) -> None:
    """One idempotent step: done when src is gone and dst is there."""
    src_there = src.exists() or src.is_symlink()
    dst_there = dst.exists() or dst.is_symlink()
    if not src_there and dst_there:
        return
    if src_there and dst_there:
        raise FolderMoveError(f"both {src} and {dst} exist")
    if not src_there:
        raise FolderMoveError(f"{src} is gone")
    os.rename(src, dst)  # same disk, checked in plan(): one instant step, nothing copied
    _fsync_dir(dst.parent)
    if src.parent != dst.parent:
        _fsync_dir(src.parent)


def _patch_settings(data_root: Path, want: dict, other: dict) -> None:
    """Set each key to want[key] when it still holds want or other; anything else is the owner's."""
    path = data_root / "settings.json"
    settings = _read_settings(data_root)
    changed = False
    for key, value in want.items():
        current = settings.get(key)
        if current == value:
            continue
        if key in settings and current != other.get(key):
            raise FolderMoveError(f"settings changed during the move: {key}")
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
        changed = True
    if changed:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        _atomic_json(path, settings, mode=mode)


def _patch_files_root(data_root: Path, want: str, other: str) -> None:
    """Files browses the default location's stored root; point it at the new files root."""
    database = Path(os.environ.get("ALLES_DB") or (data_root / "aide.db"))
    if not database.is_file():
        return
    with sqlite3.connect(database, timeout=30) as db:
        exists = db.execute(
            "select 1 from sqlite_master where type='table' and name='storage_locations'"
        ).fetchone()
        if exists:
            db.execute(
                "update storage_locations set root_path=? where id=? and root_path=?",
                (want, _DEFAULT_LOCATION, other),
            )


def _check(journal: dict) -> None:
    before = journal["inventory"]
    root = Path(journal["targets"]["root"])
    after_files = _inventory(root, journal["children"])
    if after_files != before["files"]:
        raise FolderMoveError("the files after the move don't match the files before it")
    if _tree(Path(journal["targets"]["docs"])) != before["docs"]:
        raise FolderMoveError("the docs after the move don't match the docs before it")
    if before.get("backups") and _tree(Path(journal["targets"]["backups"])) != before["backups"]:
        raise FolderMoveError("the backups after the move don't match the backups before it")


def _forward(path: Path, journal: dict, data_root: Path, step) -> None:
    if journal["state"] == "moving":
        for index, item in enumerate(journal["renames"]):
            _rename(Path(item["src"]), Path(item["dst"]))
            step(f"rename {index}")
        _check(journal)
        journal["state"] = "moved"
        _save(path, journal)
        step("moved")
    if journal["state"] == "moved":
        _patch_settings(data_root, journal["settings_new"], journal["settings_old"])
        step("settings")
        _patch_files_root(data_root, journal["targets"]["root"], journal["empty"])
        step("database")
        journal["state"] = "switched"
        _save(path, journal)
        step("switched")
    if journal["state"] == "switched":
        for leftover in journal["drop"]:
            Path(leftover).unlink(missing_ok=True)
        empty = Path(journal["empty"])
        if empty.is_dir() and not empty.is_symlink():
            try:
                empty.rmdir()
            except OSError:
                pass  # something new landed there; it stays where the owner can see it
        journal["state"] = "done"
        _save(path, journal)
        step("done")


def _backward(path: Path, journal: dict, data_root: Path, step) -> None:
    if journal["state"] != "rolling_back":
        journal["state"] = "rolling_back"
        _save(path, journal)
    _patch_settings(data_root, journal["settings_old"], journal["settings_new"])
    _patch_files_root(data_root, journal["empty"], journal["targets"]["root"])
    Path(journal["empty"]).mkdir(mode=0o700, exist_ok=True)
    for index, item in reversed(list(enumerate(journal["renames"]))):
        src, dst = Path(item["src"]), Path(item["dst"])
        if dst.exists() or dst.is_symlink():
            _rename(dst, src)
        step(f"back {index}")
    journal["state"] = "rolled_back"
    _save(path, journal)
    step("rolled_back")


def _no_step(_name: str) -> None:
    pass


def finish(layout, step=_no_step) -> str | None:
    """Finish a move a dead process left half done, or put it back when it can't finish.

    Returns None when nothing waited, "done" or "rolled_back".
    """
    path = journal_path(layout)
    if not path.exists():
        return None
    journal = _load_journal(path)
    if journal["state"] in {"done", "rolled_back"}:
        return None
    if Path(journal["data_root"]).resolve() != layout.data_root.resolve():
        raise FolderMoveError("the folder move journal belongs to another data folder")
    if journal["state"] != "rolling_back":
        try:
            _forward(path, journal, layout.data_root, step)
            return "done"
        except (FolderMoveError, OSError):
            pass
    _backward(path, journal, layout.data_root, step)
    return "rolled_back"


def move(layout, step=_no_step) -> dict:
    """Put an old layout into one folder. The caller stops the server and holds the data lock."""
    if finish(layout, step) is not None:
        journal = _load_journal(journal_path(layout))
        return {"state": journal["state"], "resumed": True}
    found = plan(layout)
    if found["state"] != "move":
        return found
    targets = _targets(layout)
    journal = {
        "version": 1,
        "id": uuid.uuid4().hex,
        "state": "moving",
        "data_root": str(layout.data_root),
        "targets": {key: str(value) for key, value in targets.items()},
        **{key: found[key] for key in ("renames", "drop", "empty", "children", "inventory")},
        "settings_old": found["settings_old"],
        "settings_new": found["settings_new"],
    }
    path = journal_path(layout)
    layout.support_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _save(path, journal)
    step("journal")
    try:
        _forward(path, journal, layout.data_root, step)
    except (FolderMoveError, OSError) as exc:
        _backward(path, journal, layout.data_root, step)
        return {"state": "rolled_back", "why": str(exc)}
    return {"state": "done", "root": journal["targets"]["root"]}


def resume_on_start(data_root: Path) -> str | None:
    """The server's first act on a native install: a reboot mid move must not start on half."""
    try:
        from services.native_install import current_layout

        layout = current_layout()
    except Exception:
        return None
    if layout is None or layout.data_root.resolve() != data_root.resolve():
        return None  # a recovery copy or another install: never touch the owner's folders
    return finish(layout)


def describe(layout) -> tuple[bool | None, str]:
    """One line for doctor and status: (ok, text). ok None is a note, not a failure."""
    try:
        found = plan(layout)
    except (FolderMoveError, OSError) as exc:
        return False, f"can't be read: {exc}"
    root = "~/" + visible_root(layout.home).relative_to(layout.home).as_posix()
    state = found["state"]
    if state == "one-folder":
        return True, f"one folder: {root}"
    if state == "move":
        return None, "old layout: alles folders move puts docs and files in " + root
    if state == "unfinished":
        return False, "a folder move stopped half way: alles folders move finishes it"
    if state == "inside-data":
        return None, "docs and files are inside the data folder: setup puts them in " + root
    return None, f"kept as is: {found['why']}"

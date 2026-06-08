"""
Files app — a browser over a configurable root dir (default data/files).
single-user, path-traversal safe. mirrors the vault_md safe-path approach.
"""
import shutil
import mimetypes
from pathlib import Path
from datetime import datetime

from core.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


def files_dir() -> Path:
    s = load_settings()
    d = s.get("files_dir") or str(ROOT / "data" / "files")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe(rel: str) -> Path:
    base = files_dir()
    p = (base / (rel or "").lstrip("/\\")).resolve()
    if base != p and base not in p.parents:
        raise ValueError("path escapes files root")
    return p


_IMG = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"}


def _entry(p: Path, base: Path) -> dict:
    st = p.stat()
    ext = p.suffix.lower().lstrip(".")
    return {
        "name": p.name,
        "path": str(p.relative_to(base)).replace("\\", "/"),
        "type": "dir" if p.is_dir() else "file",
        "size": st.st_size if p.is_file() else 0,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
        "ext": ext,
        "is_img": ext in _IMG,
    }


def listdir(rel: str = "") -> dict:
    base = files_dir()
    d = _safe(rel)
    if not d.exists() or not d.is_dir():
        raise ValueError("not a directory")
    items = []
    for c in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        if c.name.startswith("."):
            continue
        try:
            items.append(_entry(c, base))
        except Exception:
            pass  # broken symlink etc.
    return {"path": (rel or "").strip("/"), "items": items}


def read_text(rel: str, limit: int = 200_000) -> dict:
    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    raw = p.read_bytes()[:limit]
    try:
        text = raw.decode("utf-8")
        is_text = True
    except Exception:
        text, is_text = "", False
    size = p.stat().st_size
    return {"path": rel, "mime": mime, "is_text": is_text,
            "content": text, "size": size, "truncated": size > limit}


def mkdir(rel: str) -> dict:
    p = _safe(rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(p.relative_to(files_dir())).replace("\\", "/")}


def delete(rel: str) -> dict:
    p = _safe(rel)
    if not rel.strip():
        raise ValueError("won't delete the root")
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return {"ok": True}


def rename(rel: str, new_rel: str) -> dict:
    src = _safe(rel)
    dst = _safe(new_rel)
    if not src.exists():
        raise FileNotFoundError(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"ok": True, "path": str(dst.relative_to(files_dir())).replace("\\", "/")}


def save_upload(rel_dir: str, filename: str, data: bytes) -> dict:
    d = _safe(rel_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name  # strip any path from the upload name
    dst = _safe(str((Path(rel_dir) / name))) if rel_dir else _safe(name)
    dst.write_bytes(data)
    return {"ok": True, "name": name,
            "path": str(dst.relative_to(files_dir())).replace("\\", "/")}


def abspath(rel: str) -> Path:
    return _safe(rel)

"""
Files app — a browser over a configurable root dir (default data/files).
single-user, path-traversal safe. mirrors the vault_md safe-path approach.
"""

import mimetypes
import shutil
from datetime import datetime
from pathlib import Path

from core.settings import data_dir, load_settings

ROOT = Path(__file__).resolve().parent.parent


def files_dir() -> Path:
    s = load_settings()
    d = s.get("files_dir") or str(data_dir() / "files")
    p = Path(d).expanduser()
    if not p.is_absolute():
        p = ROOT / p  # relative dirs anchor to the app root, not cwd
    p = p.resolve()  # must be absolute — _safe() compares against resolved children
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


_SORT_KEYS = ("name", "size", "mtime", "type")


def listdir(rel: str = "", sort: str = "name", order: str = "") -> dict:
    base = files_dir()
    d = _safe(rel)
    if not d.exists() or not d.is_dir():
        raise ValueError("not a directory")
    items = []
    for c in d.iterdir():
        if c.name.startswith("."):
            continue
        try:
            items.append(_entry(c, base))
        except Exception:
            pass  # broken symlink etc.
    if sort not in _SORT_KEYS:
        sort = "name"
    # size/mtime default to desc (biggest/newest first); name/type default to asc
    desc = (order == "desc") if order in ("asc", "desc") else (sort in ("size", "mtime"))
    if sort == "size":
        items.sort(key=lambda e: e["size"], reverse=desc)
    elif sort == "mtime":
        items.sort(key=lambda e: e["mtime"], reverse=desc)
    elif sort == "type":
        items.sort(key=lambda e: (e["ext"], e["name"].lower()), reverse=desc)
    else:  # name
        items.sort(key=lambda e: e["name"].lower(), reverse=desc)
    # dirs always float to the top regardless of the chosen sort
    items.sort(key=lambda e: e["type"] != "dir")
    return {"path": (rel or "").strip("/"), "items": items}


def read_text(rel: str, limit: int = 200_000) -> dict:
    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    with p.open("rb") as f:
        raw = f.read(limit)  # stream just the head; don't slurp a 100MB file to hand back 200KB
    try:
        text = raw.decode("utf-8")
        is_text = True
    except Exception:
        text, is_text = "", False
    size = p.stat().st_size
    return {
        "path": rel,
        "mime": mime,
        "is_text": is_text,
        "content": text,
        "size": size,
        "truncated": size > limit,
    }


def mkdir(rel: str) -> dict:
    p = _safe(rel)
    if p.exists() and not p.is_dir():
        raise ValueError("a file with that name already exists")
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
    if dst.exists() and dst != src:
        # bare src.rename clobbers on posix / raises FileExistsError (a 500) on windows
        raise ValueError("a file or folder with that name already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"ok": True, "path": str(dst.relative_to(files_dir())).replace("\\", "/")}


def save_upload(rel_dir: str, filename: str, data: bytes) -> dict:
    name = Path(filename or "").name  # strip any path from the upload name
    if not name or set(name) <= {"."}:
        # "", ".", "..", "..." all resolve to the dir itself -> write_bytes would 500
        raise ValueError("invalid filename")
    d = _safe(rel_dir)
    d.mkdir(parents=True, exist_ok=True)
    dst = _safe(str((Path(rel_dir) / name))) if rel_dir else _safe(name)
    dst.write_bytes(data)
    return {"ok": True, "name": name, "path": str(dst.relative_to(files_dir())).replace("\\", "/")}


_TEXT_EXT = {
    "txt",
    "md",
    "markdown",
    "py",
    "js",
    "ts",
    "json",
    "csv",
    "html",
    "css",
    "log",
    "yml",
    "yaml",
    "toml",
    "ini",
    "sh",
    "xml",
    "rst",
    "tsx",
    "jsx",
}


def search(query: str, limit: int = 100) -> dict:
    """find files by name, and by content for small text files. content hits
    carry a snippet around the match. stays inside the files root, skips
    dotfiles, caps text scanning at 512KB so it can't choke on huge blobs."""
    base = files_dir()
    q = (query or "").strip().lower()
    if not q:
        return {"query": query, "results": []}
    results = []
    for p in base.rglob("*"):
        if len(results) >= limit:
            break
        rel_parts = p.relative_to(base).parts
        if any(part.startswith(".") for part in rel_parts) or not p.is_file():
            continue
        name_hit = q in p.name.lower()
        body_hit, snippet = False, ""
        if p.suffix.lower().lstrip(".") in _TEXT_EXT and p.stat().st_size <= 512_000:
            try:
                text = p.read_text("utf-8", errors="ignore")
                idx = text.lower().find(q)
                if idx != -1:
                    body_hit = True
                    s = max(0, idx - 40)
                    snippet = text[s : idx + len(q) + 40].replace("\n", " ").strip()
            except Exception:
                pass
        if name_hit or body_hit:
            e = _entry(p, base)
            e["snippet"] = snippet
            e["match"] = "both" if name_hit and body_hit else ("name" if name_hit else "content")
            results.append(e)
    results.sort(key=lambda e: (e["match"] == "content", e["name"].lower()))
    return {"query": query, "results": results[:limit]}


def _walk(base: Path):
    """yield every non-dotfile file under the root (recursive), skipping any path
    with a dot-segment. shared by smart folders + tag scans."""
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.relative_to(base).parts):
            continue
        yield p


# office/text-ish extensions that count as "documents" in the smart folder
_DOC_EXT = _TEXT_EXT | {
    "pdf",
    "doc",
    "docx",
    "odt",
    "rtf",
    "xls",
    "xlsx",
    "ods",
    "ppt",
    "pptx",
    "epub",
}

SMART_KINDS = ("recent", "images", "large", "documents")


def smart(kind: str, days: int = 30, limit: int = 200) -> dict:
    """a virtual, cross-tree view. recent = mtime within `days` (newest first);
    images / documents = by extension; large = biggest first."""
    if kind not in SMART_KINDS:
        raise ValueError(f"unknown smart folder: {kind}")
    base = files_dir()
    rows = []
    cutoff = datetime.now().timestamp() - days * 86400
    for p in _walk(base):
        try:
            e = _entry(p, base)
        except Exception:
            continue
        ext = e["ext"]
        if kind == "images" and ext not in _IMG:
            continue
        if kind == "documents" and ext not in _DOC_EXT:
            continue
        if kind == "recent" and p.stat().st_mtime < cutoff:
            continue
        rows.append(e)
    if kind == "large":
        rows.sort(key=lambda e: -e["size"])
    elif kind == "recent":
        rows.sort(key=lambda e: e["mtime"], reverse=True)
    else:
        rows.sort(key=lambda e: e["name"].lower())
    return {"kind": kind, "items": rows[:limit]}


def abspath(rel: str) -> Path:
    return _safe(rel)

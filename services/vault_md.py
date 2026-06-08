"""
Obsidian-style markdown vault: real .md files on disk + wikilinks + backlinks.
Everything is stored as plain files so the vault is portable and git-able.
"""
import os
import re
import shutil
from pathlib import Path

from core.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


def vault_dir() -> Path:
    s = load_settings()
    d = s.get("vault_dir") or str(ROOT / "data" / "vault")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe(rel: str) -> Path:
    """resolve a path inside the vault, rejecting traversal."""
    base = vault_dir()
    p = (base / (rel or "").lstrip("/\\")).resolve()
    if base not in p.parents and p != base:
        raise ValueError("path escapes vault")
    return p


_WIKILINK = re.compile(r"\[\[([^\[\]|#]+)(?:[#|][^\[\]]*)?\]\]")


def _is_md(p: Path) -> bool:
    return p.suffix.lower() in (".md", ".markdown")


def tree() -> dict:
    """nested folder/file tree of the vault (md files only)."""
    base = vault_dir()

    def walk(d: Path) -> list:
        items = []
        for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
            if child.name.startswith("."):
                continue
            rel = str(child.relative_to(base)).replace("\\", "/")
            if child.is_dir():
                items.append({"type": "dir", "name": child.name, "path": rel, "children": walk(child)})
            elif _is_md(child):
                items.append({"type": "file", "name": child.stem, "path": rel})
        return items

    return {"path": str(base), "items": walk(base)}


def read(rel: str) -> dict:
    p = _safe(rel)
    if not p.exists() or not p.is_file():
        return {"path": rel, "content": "", "exists": False}
    return {"path": rel, "content": p.read_text("utf-8", errors="replace"), "exists": True}


def write(rel: str, content: str) -> dict:
    p = _safe(rel)
    if p.suffix == "":
        p = p.with_suffix(".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or "", "utf-8")
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def create(rel: str, content: str = "") -> dict:
    p = _safe(rel)
    if p.suffix == "":
        p = p.with_suffix(".md")
    if p.exists():
        return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True, "existed": True}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or f"# {p.stem}\n\n", "utf-8")
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def delete(rel: str) -> dict:
    p = _safe(rel)
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return {"ok": True}


def rename(rel: str, new_rel: str) -> dict:
    src = _safe(rel)
    dst = _safe(new_rel)
    # only auto-append .md when renaming a FILE (folders keep their plain name)
    if src.is_file() and dst.suffix == "":
        dst = dst.with_suffix(".md")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"path": str(dst.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def _all_md() -> list[Path]:
    base = vault_dir()
    return [p for p in base.rglob("*") if p.is_file() and _is_md(p) and not p.name.startswith(".")]


def note_names() -> list[str]:
    """all note stems, for [[ autocomplete + graph."""
    return sorted({p.stem for p in _all_md()})


def search(q: str, limit: int = 20) -> list[dict]:
    ql = (q or "").lower()
    base = vault_dir()
    out = []
    for p in _all_md():
        if not ql or ql in p.stem.lower():
            out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")})
    out.sort(key=lambda r: (not r["name"].lower().startswith(ql), len(r["name"])))
    return out[:limit]


def backlinks(name: str) -> list[dict]:
    """notes that contain a [[name]] link to this note."""
    base = vault_dir()
    target = (name or "").strip().lower()
    out = []
    for p in _all_md():
        if p.stem.lower() == target:
            continue
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for m in _WIKILINK.finditer(text):
            if m.group(1).strip().lower() == target:
                # grab a little surrounding context
                start = max(0, m.start() - 40)
                ctx = " ".join(text[start:m.end() + 40].split())
                out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/"), "context": ctx})
                break
    return out


def outgoing_links(rel: str) -> list[str]:
    p = _safe(rel)
    if not p.exists():
        return []
    text = p.read_text("utf-8", errors="replace")
    return sorted({m.group(1).strip() for m in _WIKILINK.finditer(text)})


def create_folder(rel: str) -> dict:
    p = _safe(rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p.relative_to(vault_dir())).replace("\\", "/"), "ok": True}


def find_asset(name: str) -> str | None:
    """resolve an embed target (image/file) by relative path or bare name."""
    base = vault_dir()
    name = (name or "").strip()
    try:
        p = _safe(name)
        if p.is_file():
            return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        pass
    target = name.lower()
    for f in base.rglob("*"):
        if f.is_file() and not f.name.startswith(".") and (f.name.lower() == target or f.stem.lower() == target):
            return str(f.relative_to(base)).replace("\\", "/")
    return None


def file_bytes(rel: str):
    import mimetypes
    p = _safe(rel)
    if not p.is_file():
        raise ValueError("not a file")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return p.read_bytes(), mime


def full_text_search(q: str, limit: int = 50) -> list[dict]:
    """search note names AND contents, with a snippet of context."""
    base = vault_dir()
    ql = (q or "").strip().lower()
    if not ql:
        return []
    out = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        low = text.lower()
        idx = low.find(ql)
        in_name = ql in p.stem.lower()
        if idx < 0 and not in_name:
            continue
        ctx = ""
        if idx >= 0:
            s = max(0, idx - 40)
            ctx = " ".join(text[s:idx + len(ql) + 50].split())
        out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/"), "context": ctx})
        if len(out) >= limit:
            break
    out.sort(key=lambda r: (ql not in r["name"].lower(), r["name"].lower()))
    return out


_TAG = re.compile(r"(?:^|\s)#([A-Za-z0-9][A-Za-z0-9_/\-]*)")


def all_tags() -> list[dict]:
    counts: dict[str, int] = {}
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for t in {m.group(1) for m in _TAG.finditer(text)}:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def notes_with_tag(tag: str) -> list[dict]:
    base = vault_dir()
    target = (tag or "").lstrip("#").lower()
    out = []
    for p in _all_md():
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        if any(m.group(1).lower() == target for m in _TAG.finditer(text)):
            out.append({"name": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")})
    return out


def graph() -> dict:
    """nodes = notes, edges = resolved [[wikilinks]] between them."""
    base = vault_dir()
    files = _all_md()
    by_stem = {p.stem.lower(): p.stem for p in files}
    nodes = [{"id": p.stem, "path": str(p.relative_to(base)).replace("\\", "/")} for p in files]
    edges = []
    for p in files:
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        for tgt in {m.group(1).strip() for m in _WIKILINK.finditer(text)}:
            res = by_stem.get(tgt.lower())
            if res and res != p.stem:
                edges.append({"source": p.stem, "target": res})
    # degree for sizing
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)
    return {"nodes": nodes, "edges": edges}

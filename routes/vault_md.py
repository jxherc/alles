"""
Thin docs API over the markdown vault. Real editing happens in Obsidian — the app only
READS/BROWSES docs (tree, read, search, tags, backlinks, semantic ask) and does basic file
management (create / rename / delete / folder). The heavy in-browser editor (live/source CM,
AI-edit, graph, canvas, kanban, dataview, base, properties, comments, revisions, periodic,
templates, import/export, publish, etc.) was removed — Obsidian does all that better.

The `services/vault_md.py` SERVICE layer is untouched (agents, search, notes all use it).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services import vault_md

router = APIRouter(prefix="/api/vault-md")


def _norm_path(rel: str) -> str:
    from pathlib import PurePosixPath

    rel = (rel or "").replace("\\", "/")
    return rel if PurePosixPath(rel).suffix else rel + ".md"


def _is_note(path):
    # notes live under Notes/ and are indexed as the "note" kind (keyed by stem), not "doc",
    # so they aren't double-indexed. see services/notes_vault.py
    return (path or "").replace("\\", "/").startswith("Notes/")


def _note_stem(path):
    from pathlib import PurePosixPath
    return PurePosixPath((path or "").replace("\\", "/")).stem


# keep the reusable text index in sync with the vault (best-effort, never breaks a write)
def _reindex_doc(path, content):
    try:
        from core.database import SessionLocal
        from services import textindex

        db = SessionLocal()
        try:
            if _is_note(path):
                from services import personal_index
                personal_index.index_record(db, "note", _note_stem(path))
            else:
                textindex.index(db, "doc", path, content)
        finally:
            db.close()
    except Exception:
        pass


def _unindex_doc(path):
    try:
        from core.database import SessionLocal
        from services import textindex

        db = SessionLocal()
        try:
            if _is_note(path):
                from services import personal_index
                personal_index.remove_record(db, "note", _note_stem(path))
            else:
                textindex.remove(db, "doc", path)
        finally:
            db.close()
    except Exception:
        pass


# ── read / browse ────────────────────────────────────────────────────────────
@router.get("/tree")
def tree():
    return vault_md.tree()


@router.get("/file")
def read_file(path: str):
    try:
        return vault_md.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/raw")
def raw_asset(path: str):
    """serve an embedded asset (image/pdf/etc.) by path or bare name — for ![[ ]] embeds."""
    resolved = vault_md.find_asset(path) or path
    try:
        data, mime = vault_md.file_bytes(resolved)
    except ValueError:
        raise HTTPException(404, "asset not found")
    return Response(content=data, media_type=mime, headers={"cache-control": "no-cache"})


@router.get("/search")
def search(q: str = ""):
    return {"results": vault_md.search(q)}


@router.get("/grep")
def grep(q: str = ""):
    return {"results": vault_md.full_text_search(q)}


@router.get("/tags")
def tags():
    return {"tags": vault_md.all_tags()}


@router.get("/tag")
def by_tag(tag: str):
    return {"notes": vault_md.notes_with_tag(tag)}


@router.get("/preview")
def preview_note(name: str):
    """resolve a wikilink name → a short excerpt for the hover preview."""
    name = (name or "").strip()
    if not name:
        return {"found": False, "excerpt": ""}
    hits = vault_md.search(name)
    hit = next((h for h in hits if (h.get("name", "").lower() == name.lower())), None)
    if not hit and hits:
        hit = hits[0]
    if not hit:
        return {"found": False, "excerpt": ""}
    doc = vault_md.read(hit["path"])
    body = doc.get("content", "")
    try:
        _, body = vault_md.parse_frontmatter(body)
    except Exception:
        pass
    return {"found": True, "path": hit["path"], "title": hit.get("name", name),
            "excerpt": body.strip()[:240]}


@router.get("/backlinks")
def backlinks(name: str):
    return {"backlinks": vault_md.backlinks(name)}


@router.get("/unlinked")
def unlinked(name: str):
    return {"mentions": vault_md.unlinked_mentions(name)}


@router.get("/names")
def names():
    return {"names": vault_md.note_names()}


@router.get("/ask")
def ask_vault(q: str = "", db: DbSession = Depends(get_db)):
    """ask-anything over the vault — semantic retrieval via the shared text index."""
    from routes.textindex import _collect_docs
    from services import textindex

    if not textindex.stats(db).get("doc"):
        textindex.reindex_kind(db, "doc", _collect_docs())
    hits = textindex.search(db, q, kind="doc", k=6) if q else []
    return {"q": q, "sources": hits}


# ── basic file management (content editing happens in Obsidian) ───────────────
class PathBody(BaseModel):
    path: str
    content: str = ""


@router.post("/file")
def create_file(body: PathBody):
    try:
        out = vault_md.create(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _reindex_doc(out.get("path", _norm_path(body.path)), body.content or "")
    return out


@router.delete("/file")
def delete_file(path: str):
    try:
        out = vault_md.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _unindex_doc(_norm_path(path))
    return out


class RenameBody(BaseModel):
    path: str
    new_path: str


@router.post("/rename")
def rename_file(body: RenameBody):
    try:
        out = vault_md.rename(body.path, body.new_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    new_path = out.get("path", _norm_path(body.new_path))
    is_file = new_path.lower().endswith((".md", ".markdown"))
    out["links_rewritten"] = 0
    if is_file:
        from pathlib import PurePosixPath

        old_norm = _norm_path(body.path)
        old_stem = PurePosixPath(old_norm).stem
        new_stem = PurePosixPath(new_path).stem
        if old_stem and new_stem and old_stem.lower() != new_stem.lower():
            out["links_rewritten"] = len(vault_md.rewrite_links(old_stem, new_stem))
        _unindex_doc(old_norm)
        _reindex_doc(new_path, vault_md.read(new_path).get("content", ""))
    else:
        # folder rename: reindex each child at its new path (old entries get cleaned by reconcile)
        base = vault_md.vault_dir()
        old_pre = body.path.strip("/") + "/"
        new_pre = new_path.strip("/") + "/"
        for p in (base / new_path).rglob("*.md"):
            rel_new = str(p.relative_to(base)).replace("\\", "/")
            rel_old = old_pre + rel_new[len(new_pre):]
            _unindex_doc(rel_old)
            _reindex_doc(rel_new, p.read_text("utf-8", errors="replace"))
    return out


class FolderBody(BaseModel):
    path: str


@router.post("/folder")
def make_folder(body: FolderBody):
    try:
        return vault_md.create_folder(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))

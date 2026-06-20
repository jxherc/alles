import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import DocComment, get_db
from services import share, vault_md

router = APIRouter(prefix="/api/vault-md")


class PublishFolderBody(BaseModel):
    folder: str = ""


@router.post("/publish-folder")
def publish_folder(body: PublishFolderBody, db: DbSession = Depends(get_db)):
    """publish every doc in a folder as a navigable read-only site (3c, uses 1a)."""
    base = vault_md.vault_dir()
    folder = (body.folder or "").strip().strip("/")
    out = []
    for p in base.rglob("*.md"):
        rel = str(p.relative_to(base)).replace("\\", "/")
        if any(part.startswith((".", "_")) for part in rel.split("/")):
            continue
        in_folder = rel.startswith(folder + "/") if folder else "/" not in rel
        if not in_folder:
            continue
        s = share.mint(db, "doc", rel)
        out.append({"path": rel, "token": s.token, "url": f"/s/{s.token}"})
    return {"published": out, "count": len(out)}


# 1c: keep the reusable text index in sync with the vault (best-effort, never breaks a save)
def _reindex_doc(path, content):
    try:
        from core.database import SessionLocal
        from services import textindex

        db = SessionLocal()
        try:
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
            textindex.remove(db, "doc", path)
        finally:
            db.close()
    except Exception:
        pass


def _docs_ai(db):
    """resolve (endpoint, model) for docs AI — honour the `docs_ai_model` setting if it
    names a model an enabled endpoint serves, else fall back to the first enabled endpoint."""
    from core.database import ModelEndpoint
    from core.settings import load_settings

    pref = (load_settings().get("docs_ai_model") or "").strip()
    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    if pref:
        for ep in eps:
            if pref in ep.models_list():
                return ep, pref
    ep = eps[0] if eps else None
    if not ep:
        return None, ""
    return ep, (ep.models_list()[0] if ep.models_list() else "")


@router.get("/export-docx")
def export_docx(path: str):
    cur = vault_md.read(path)
    if not cur.get("exists"):
        raise HTTPException(404, "note not found")
    try:
        from services.docx_export import md_to_docx
    except Exception:
        raise HTTPException(500, "python-docx not installed (pip install python-docx)")
    title = path.split("/")[-1].rsplit(".", 1)[0]
    data = md_to_docx(cur["content"], title)
    fname = (title or "note").replace('"', "") + ".docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"content-disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/tree")
def tree():
    return vault_md.tree()


@router.get("/raw")
def raw_asset(path: str):
    """serve an embedded asset (image/pdf/etc.) by path or bare name — for ![[ ]] embeds."""
    resolved = vault_md.find_asset(path) or path
    try:
        data, mime = vault_md.file_bytes(resolved)
    except ValueError:
        raise HTTPException(404, "asset not found")
    return Response(content=data, media_type=mime, headers={"cache-control": "no-cache"})


@router.get("/file")
def read_file(path: str):
    try:
        return vault_md.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class WriteBody(BaseModel):
    path: str
    content: str = ""


_REV_GAP = 300  # min seconds between automatic snapshots of the same doc
_REV_KEEP = 50  # revisions kept per doc


def _norm_path(rel: str) -> str:
    from pathlib import PurePosixPath

    rel = (rel or "").replace("\\", "/")
    return rel if PurePosixPath(rel).suffix else rel + ".md"


def _snapshot(rel: str, force: bool = False):
    """store the doc's current on-disk content as a revision (its pre-change
    state). autosave fires every keystroke pause, so unforced snapshots are
    rate-limited — you get the pre-session state plus one every ~5 minutes."""
    from datetime import datetime

    from core.database import DocRevision, SessionLocal

    rel = _norm_path(rel)
    try:
        cur = vault_md.read(rel)
    except ValueError:
        return
    if not cur.get("exists"):
        return
    db = SessionLocal()
    try:
        last = (
            db.query(DocRevision)
            .filter_by(path=rel)
            .order_by(DocRevision.created_at.desc())
            .first()
        )
        if last and last.content == cur["content"]:
            return
        if not force and last and (datetime.utcnow() - last.created_at).total_seconds() < _REV_GAP:
            return
        db.add(DocRevision(path=rel, content=cur["content"]))
        for old in (
            db.query(DocRevision)
            .filter_by(path=rel)
            .order_by(DocRevision.created_at.desc())
            .offset(_REV_KEEP)
            .all()
        ):
            db.delete(old)
        db.commit()
    finally:
        db.close()


@router.put("/file")
async def write_file(body: WriteBody):
    try:
        _snapshot(body.path)
        out = vault_md.write(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        from services.automations import on_doc_saved

        await on_doc_saved(out.get("path", body.path), body.content or "")
    except Exception:
        pass  # automations must never break a save
    _reindex_doc(out.get("path", body.path), body.content or "")
    return out


class PathBody(BaseModel):
    path: str
    content: str = ""


@router.post("/file")
def create_file(body: PathBody):
    try:
        return vault_md.create(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/file")
def delete_file(path: str):
    try:
        out = vault_md.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _unindex_doc(path)
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
    # carry the history along with the doc
    from core.database import DocRevision, SessionLocal

    db = SessionLocal()
    try:
        db.query(DocRevision).filter_by(path=_norm_path(body.path)).update({"path": new_path})
        db.commit()
    finally:
        db.close()
    # renaming a FILE changes its [[wikilink]] name → rewrite every backlink so the
    # graph doesn't silently break. snapshot affected notes first so it's undoable.
    out["links_rewritten"] = 0
    if new_path.lower().endswith((".md", ".markdown")):
        from pathlib import PurePosixPath

        old_stem = PurePosixPath(_norm_path(body.path)).stem
        new_stem = PurePosixPath(new_path).stem
        if old_stem and new_stem and old_stem.lower() != new_stem.lower():
            for bl in vault_md.backlinks(old_stem):
                _snapshot(bl["path"], force=True)
            out["links_rewritten"] = len(vault_md.rewrite_links(old_stem, new_stem))
    _unindex_doc(_norm_path(body.path))
    _reindex_doc(new_path, vault_md.read(new_path).get("content", ""))
    return out


class ExtractTodosBody(BaseModel):
    path: str


@router.post("/extract-todos")
async def extract_todos(body: ExtractTodosBody):
    """AI-pull action items out of a doc and create real tasks from them."""
    import json as _json

    from core.database import SessionLocal, Task
    from services.llm import simple_complete

    try:
        doc = vault_md.read(_norm_path(body.path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not doc.get("exists") or not (doc.get("content") or "").strip():
        raise HTTPException(404, "doc is empty or missing")

    db = SessionLocal()
    try:
        ep, model = _docs_ai(db)
        if not ep:
            raise HTTPException(400, "no model endpoint configured")
        if not model:
            raise HTTPException(400, "no model available")
        prompt = [
            {
                "role": "system",
                "content": (
                    "Extract actionable to-do items from the document. Reply with ONLY a JSON "
                    "array of short task title strings, no prose, no code fences. If there is "
                    "nothing actionable, reply []."
                ),
            },
            {"role": "user", "content": doc["content"][:8000]},
        ]
        raw = await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=400)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            items = _json.loads(raw)
            assert isinstance(items, list)
        except Exception:
            raise HTTPException(502, "model returned unparseable output — try again")
        created = []
        for title in items[:20]:
            title = str(title).strip()[:300]
            if title:
                t = Task(title=title)
                db.add(t)
                created.append(title)
        db.commit()
        return {"created": len(created), "tasks": created}
    finally:
        db.close()


@router.get("/board")
def get_board(path: str):
    cur = vault_md.read(_norm_path(path))
    return {"path": _norm_path(path), "columns": vault_md.parse_board(cur.get("content", "") or "")}


class BoardAddBody(BaseModel):
    path: str
    column: str
    text: str


@router.post("/board/add")
def board_add(body: BoardAddBody):
    _snapshot(body.path)
    try:
        return vault_md.board_add_card(_norm_path(body.path), body.column, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))


class BoardMoveBody(BaseModel):
    path: str
    line: int
    to_col: str


@router.post("/board/move")
def board_move(body: BoardMoveBody):
    _snapshot(body.path)
    try:
        return vault_md.board_move_card(_norm_path(body.path), body.line, body.to_col)
    except ValueError as e:
        raise HTTPException(400, str(e))


class QueryBody(BaseModel):
    filters: list = []
    sort: dict | None = None
    limit: int = 0


@router.post("/query")
def query(body: QueryBody):
    rows = vault_md.query_notes(body.filters, body.sort, body.limit or None)
    return {"results": rows, "count": len(rows)}


class PeriodicBody(BaseModel):
    kind: str
    date: str = ""  # optional ISO YYYY-MM-DD; default today


@router.post("/periodic")
def periodic(body: PeriodicBody):
    from datetime import date as _date

    d = None
    if body.date:
        try:
            d = _date.fromisoformat(body.date)
        except ValueError:
            raise HTTPException(400, "bad date — use YYYY-MM-DD")
    try:
        return vault_md.open_or_create_periodic(body.kind, d)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/properties")
def get_properties(path: str):
    cur = vault_md.read(_norm_path(path))
    props, _ = vault_md.parse_frontmatter(cur.get("content", "") or "")
    return {"path": _norm_path(path), "properties": props, "exists": cur.get("exists", False)}


class PropsBody(BaseModel):
    path: str
    properties: dict = {}


@router.put("/properties")
def put_properties(body: PropsBody):
    cur = vault_md.read(_norm_path(body.path))
    new_content = vault_md.set_frontmatter(cur.get("content", "") or "", body.properties)
    _snapshot(body.path)
    out = vault_md.write(body.path, new_content)
    return {
        "ok": True,
        "path": out.get("path", _norm_path(body.path)),
        "properties": body.properties,
    }


@router.get("/revisions")
def list_revisions(path: str):
    from core.database import DocRevision, SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(DocRevision)
            .filter_by(path=_norm_path(path))
            .order_by(DocRevision.created_at.desc())
            .all()
        )
        return [
            {"id": r.id, "created_at": r.created_at.isoformat(), "size": len(r.content or "")}
            for r in rows
        ]
    finally:
        db.close()


@router.get("/revisions/{rid}")
def get_revision(rid: str):
    from core.database import DocRevision, SessionLocal

    db = SessionLocal()
    try:
        r = db.get(DocRevision, rid)
        if not r:
            raise HTTPException(404)
        return {
            "id": r.id,
            "path": r.path,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
    finally:
        db.close()


@router.post("/revisions/{rid}/restore")
def restore_revision(rid: str):
    from core.database import DocRevision, SessionLocal

    db = SessionLocal()
    try:
        r = db.get(DocRevision, rid)
        if not r:
            raise HTTPException(404)
        path, content = r.path, r.content
    finally:
        db.close()
    _snapshot(path, force=True)  # the state being replaced becomes a revision
    out = vault_md.write(path, content)
    return {"ok": True, "path": out.get("path", path)}


@router.get("/diff")
def diff_revision(path: str, a: str = "", b: str = ""):
    """unified diff between revision `a` and `b`. empty/'current' b = the live file."""
    import difflib

    from core.database import DocRevision, SessionLocal

    db = SessionLocal()
    try:
        old = (db.get(DocRevision, a).content if a and db.get(DocRevision, a) else "") or ""
        if not b or b == "current":
            new = vault_md.read(_norm_path(path)).get("content", "") or ""
            blabel = "current"
        else:
            rb = db.get(DocRevision, b)
            new = (rb.content if rb else "") or ""
            blabel = b[:8]
    finally:
        db.close()
    d = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=a[:8] if a else "empty",
            tofile=blabel,
        )
    )
    return {"diff": d}


@router.get("/search")
def search(q: str = ""):
    return {"results": vault_md.search(q)}


@router.get("/ask")
def ask_vault(q: str = "", db: DbSession = Depends(get_db)):
    """ask-anything over the vault (3d) — semantic retrieval via the 1c text index."""
    from routes.textindex import _collect_docs
    from services import textindex

    if not textindex.stats(db).get("doc"):
        textindex.reindex_kind(db, "doc", _collect_docs())
    hits = textindex.search(db, q, kind="doc", k=6) if q else []
    return {"q": q, "sources": hits}


class ClipBody(BaseModel):
    url: str = ""
    title: str = ""
    content: str = ""


@router.post("/clip")
def web_clip(body: ClipBody):
    """web-clipper target (3d): save a clipped page as a note under clips/."""
    title = (body.title or "clip").strip() or "clip"
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:60] or "clip"
    md = f"# {title}\n\n"
    if body.url:
        md += f"source: {body.url}\n\n"
    md += body.content or ""
    out = vault_md.write(f"clips/{safe}", md)
    return {"ok": True, "path": out.get("path", f"clips/{safe}.md")}


@router.get("/clipper-bookmarklet")
def clipper_bookmarklet(request: Request):
    """the bookmarklet JS the user drags to their bookmarks bar (3d).
    origin is taken from the request so the dragged bookmarklet posts back to this instance."""
    origin = str(request.base_url).rstrip("/")
    js = (
        "javascript:(function(){var t=document.title,u=location.href,"
        "s=window.getSelection().toString()||document.body.innerText.slice(0,4000);"
        "fetch('"
        + origin
        + "/api/vault-md/clip',{method:'POST',headers:{'content-type':'application/json'},"
        "body:JSON.stringify({url:u,title:t,content:s})}).then(()=>alert('clipped to alles'));})()"
    )
    return {"bookmarklet": js}


class FormBody(BaseModel):
    path: str = ""
    target: str = ""
    fields: list[str] = []
    values: dict = {}


@router.post("/form-submit")
def form_submit(body: FormBody):
    """append a form submission as a row to the target note (3d form blocks)."""
    target = (body.target or "").strip()
    if not target:
        raise HTTPException(400, "target required")
    _snapshot(target)
    out = vault_md.append_form_row(target, body.values or {}, body.fields or None)
    _reindex_doc(out["path"], vault_md.read(out["path"]).get("content", ""))
    return out


# ---- inline comments (3e) ----
class CommentBody(BaseModel):
    path: str = ""
    anchor: str = ""
    body: str = ""
    author: str = "me"
    parent_id: str | None = None


def _comment_dict(c):
    return {
        "id": c.id,
        "doc": c.doc,
        "anchor": c.anchor or "",
        "body": c.body or "",
        "author": c.author or "me",
        "parent_id": c.parent_id,
        "resolved": bool(c.resolved),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.post("/comments")
def add_comment(body: CommentBody, db: DbSession = Depends(get_db)):
    """create a thread root (with path+anchor) or a reply (with parent_id)."""
    if not (body.body or "").strip():
        raise HTTPException(400, "comment body required")
    if body.parent_id:
        parent = db.query(DocComment).filter_by(id=body.parent_id).first()
        if not parent:
            raise HTTPException(404, "parent comment not found")
        root = (
            parent
            if parent.parent_id is None
            else db.query(DocComment).filter_by(id=parent.parent_id).first()
        )
        c = DocComment(
            doc=root.doc,
            anchor=root.anchor,
            body=body.body.strip(),
            author=body.author or "me",
            parent_id=root.id,
        )
    else:
        if not (body.path or "").strip():
            raise HTTPException(400, "path required")
        c = DocComment(
            doc=_norm_path(body.path),
            anchor=body.anchor or "",
            body=body.body.strip(),
            author=body.author or "me",
            parent_id=None,
        )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _comment_dict(c)


@router.get("/comments")
def list_comments(path: str, db: DbSession = Depends(get_db)):
    """threads for a doc — each root plus its replies, with an anchor-orphaned flag."""
    doc = _norm_path(path)
    content = vault_md.read(doc).get("content", "")
    rows = db.query(DocComment).filter_by(doc=doc).order_by(DocComment.created_at.asc()).all()
    threads = []
    for root in [c for c in rows if c.parent_id is None]:
        t = _comment_dict(root)
        t["replies"] = [_comment_dict(c) for c in rows if c.parent_id == root.id]
        t["orphaned"] = bool(root.anchor) and root.anchor not in content
        threads.append(t)
    return {"threads": threads}


@router.post("/comments/{cid}/resolve")
def resolve_comment(cid: str, db: DbSession = Depends(get_db)):
    """toggle the resolved flag on a thread (always via its root)."""
    c = db.query(DocComment).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "comment not found")
    root = c if c.parent_id is None else db.query(DocComment).filter_by(id=c.parent_id).first()
    root.resolved = not bool(root.resolved)
    db.commit()
    return {"id": root.id, "resolved": bool(root.resolved)}


@router.delete("/comments/{cid}")
def delete_comment(cid: str, db: DbSession = Depends(get_db)):
    """delete a comment; deleting a root also drops its replies."""
    c = db.query(DocComment).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "comment not found")
    if c.parent_id is None:
        db.query(DocComment).filter_by(parent_id=c.id).delete()
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/block")
def get_block(path: str, id: str):
    """resolve a synced-block reference note#^id → its text (3b)."""
    return vault_md.find_block(path, id)


@router.get("/theme-css")
def get_theme_css():
    return {"css": vault_md.theme_css_read()}


class ThemeBody(BaseModel):
    css: str = ""


@router.put("/theme-css")
def put_theme_css(body: ThemeBody):
    """save a per-vault CSS snippet (2e) — auto-injected on the docs view."""
    return vault_md.theme_css_write(body.css)


@router.get("/canvases")
def list_canvases():
    return {"canvases": vault_md.canvas_list()}


@router.get("/canvas")
def read_canvas(path: str):
    return vault_md.canvas_read(path)


class CanvasBody(BaseModel):
    path: str
    nodes: list = []
    edges: list = []


@router.put("/canvas")
def write_canvas(body: CanvasBody):
    """save a spatial canvas (.canvas JSON) (2d)."""
    try:
        return vault_md.canvas_write(body.path, body.nodes, body.edges)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/base")
def base_view(folder: str = "", sort_field: str = "", sort_dir: str = "asc"):
    """folder-as-database view (2c)."""
    sort = {"field": sort_field, "dir": sort_dir} if sort_field else None
    return vault_md.base_view(folder, sort)


class CellBody(BaseModel):
    path: str
    key: str
    value: str = ""


@router.post("/base-cell")
async def base_cell(body: CellBody):
    """edit one Base cell → writes back to the note's frontmatter (2c).
    also fires doc automations so a Base edit can trigger rules (3d in-DB automations)."""
    _snapshot(body.path)
    props = vault_md.set_cell(body.path, body.key, body.value)
    try:
        from services.automations import on_doc_saved

        await on_doc_saved(_norm_path(body.path), vault_md.read(body.path).get("content", ""))
    except Exception:
        pass
    return {"ok": True, "path": _norm_path(body.path), "properties": props}


@router.get("/base-rollup")
def base_rollup(folder: str = "", relation: str = "", target: str = "", agg: str = "count"):
    return {"rows": vault_md.base_rollup(folder, relation, target or None, agg)}


class QueryBlockBody(BaseModel):
    spec: str = ""


@router.post("/query-block")
def query_block(body: QueryBlockBody):
    """run an inline ```query``` fence spec (2b)."""
    return vault_md.query_block(body.spec)


@router.get("/views")
def get_views():
    from core.settings import load_settings

    return {"views": load_settings().get("docs_saved_views", [])}


class ViewBody(BaseModel):
    name: str
    spec: str = ""


@router.post("/views")
def save_view(body: ViewBody):
    """save (or update) a named query view (2b)."""
    from core.settings import load_settings, save_settings

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    views = [v for v in load_settings().get("docs_saved_views", []) if v.get("name") != name]
    views.append({"name": name, "spec": body.spec})
    save_settings({"docs_saved_views": views})
    return {"ok": True, "views": views}


@router.delete("/views")
def delete_view(name: str):
    from core.settings import load_settings, save_settings

    views = [v for v in load_settings().get("docs_saved_views", []) if v.get("name") != name]
    save_settings({"docs_saved_views": views})
    return {"ok": True, "views": views}


@router.get("/bookmarks")
def get_bookmarks():
    from core.settings import load_settings

    return {"bookmarks": load_settings().get("docs_bookmarks", [])}


class BookmarkBody(BaseModel):
    path: str
    title: str = ""


@router.post("/bookmarks")
def toggle_bookmark(body: BookmarkBody):
    """toggle a doc bookmark (2a). returns the new state + full list."""
    from core.settings import load_settings, save_settings

    bms = list(load_settings().get("docs_bookmarks", []))
    if any(b.get("path") == body.path for b in bms):
        bms = [b for b in bms if b.get("path") != body.path]
        on = False
    else:
        bms.append({"path": body.path, "title": body.title or body.path})
        on = True
    save_settings({"docs_bookmarks": bms})
    return {"bookmarked": on, "bookmarks": bms}


@router.get("/preview")
def preview_note(name: str):
    """resolve a wikilink name → a short excerpt for the hover preview (2a)."""
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
    return {
        "found": True,
        "path": hit["path"],
        "title": hit.get("name", name),
        "excerpt": body.strip()[:240],
    }


@router.get("/backlinks")
def backlinks(name: str):
    return {"backlinks": vault_md.backlinks(name)}


@router.get("/names")
def names():
    return {"names": vault_md.note_names()}


@router.get("/grep")
def grep(q: str = ""):
    return {"results": vault_md.full_text_search(q)}


@router.get("/tags")
def tags():
    return {"tags": vault_md.all_tags()}


@router.get("/tag")
def by_tag(tag: str):
    return {"notes": vault_md.notes_with_tag(tag)}


@router.get("/graph")
def graph(tag: str = "", folder: str = ""):
    return vault_md.graph(tag or None, folder or None)


@router.get("/local-graph")
def local_graph(name: str, depth: int = 1):
    return vault_md.local_graph(name, depth)


@router.get("/slash-commands")
def slash_commands(q: str = ""):
    return {"commands": vault_md.filter_slash_commands(q)}


@router.post("/asset")
async def upload_asset(file: UploadFile = File(...)):
    """pasted/dropped image → saved under _assets/, returns the embed path."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "file too big (25MB max)")
    return vault_md.save_asset(file.filename or "image.png", data)


@router.get("/tasks")
def tasks(open_only: bool = False):
    return {"tasks": vault_md.all_tasks(include_done=not open_only)}


class TaskToggleBody(BaseModel):
    path: str
    line: int
    done: bool


@router.post("/task")
def toggle_task(body: TaskToggleBody):
    try:
        return vault_md.set_task(body.path, body.line, body.done)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/templates")
def templates():
    return {"templates": vault_md.list_templates()}


@router.get("/unlinked")
def unlinked(name: str):
    return {"mentions": vault_md.unlinked_mentions(name)}


class YoutubeBody(BaseModel):
    url: str
    summarize: bool = True


@router.post("/youtube")
async def youtube_to_note(body: YoutubeBody):
    """YouTube URL → transcript → (optional) AI summary → a new doc."""
    import re as _re

    from services import youtube

    vid = youtube.extract_video_id(body.url)
    if not vid:
        raise HTTPException(400, "that doesn't look like a YouTube URL")
    try:
        title, transcript = await youtube.fetch_transcript(vid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(502, "couldn't reach YouTube to fetch the transcript")

    summary = ""
    if body.summarize:
        from core.database import SessionLocal
        from services.llm import simple_complete

        db = SessionLocal()
        try:
            ep, model = _docs_ai(db)
        finally:
            db.close()
        if ep and model:
            try:
                prompt = [
                    {
                        "role": "system",
                        "content": (
                            "Turn this video transcript into clean markdown notes: a one-line **TL;DR**, "
                            "then the key points as bullets, then any notable takeaways or quotes. "
                            "No preamble, no code fences."
                        ),
                    },
                    {"role": "user", "content": transcript[:14000]},
                ]
                summary = (
                    await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=900)
                ).strip()
            except Exception:
                summary = ""

    safe = (_re.sub(r'[\\/:*?"<>|#\[\]]+', " ", title).strip() or f"youtube-{vid}")[:80].strip()
    link = f"https://youtu.be/{vid}"
    md = f"# {safe}\n\n[{link}]({link})\n\n"
    md += (
        (summary + "\n\n## transcript\n\n" + transcript + "\n")
        if summary
        else ("## transcript\n\n" + transcript + "\n")
    )

    existing = {n.lower() for n in vault_md.note_names()}
    path = safe
    if safe.lower() in existing:
        i = 1
        while f"{safe}-{i}".lower() in existing:
            i += 1
        path = f"{safe}-{i}"
    out = vault_md.create(path, md)
    return {"path": out.get("path", path + ".md"), "name": safe, "summarized": bool(summary)}


@router.post("/import")
async def import_doc(file: UploadFile = File(...)):
    """import .md/.txt/.docx/.html/.pdf → a new markdown doc."""
    from services import doc_import

    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "file too big (25MB max)")
    try:
        res = doc_import.import_document(file.filename or "imported", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(500, "couldn't read that file — it may be corrupt")
    # pick a free name so an import never clobbers an existing doc
    base = res["name"] or "imported"
    existing = {n.lower() for n in vault_md.note_names()}
    path = base
    if base.lower() in existing:
        i = 1
        while f"{base}-{i}".lower() in existing:
            i += 1
        path = f"{base}-{i}"
    out = vault_md.create(path, res["content"])
    return {"path": out.get("path", path + ".md"), "name": base}


class FolderBody(BaseModel):
    path: str


@router.post("/folder")
def make_folder(body: FolderBody):
    try:
        return vault_md.create_folder(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class AiSnippetBody(BaseModel):
    text: str
    action: str = "rewrite"


# context-menu AI actions act on the selected text only (not the whole doc like ai-edit)
_SNIPPET_PROMPTS = {
    "rewrite": "Rewrite the text to read more clearly and naturally, keeping its meaning and any markdown.",
    "summarize": "Summarize the text in one or two short sentences.",
    "fix": "Fix spelling and grammar in the text. Keep the wording and any markdown otherwise unchanged.",
}


@router.post("/ai-snippet")
async def ai_snippet(body: AiSnippetBody):
    from core.database import SessionLocal
    from services.llm import simple_complete

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "no text selected")
    sys_prompt = _SNIPPET_PROMPTS.get(body.action, _SNIPPET_PROMPTS["rewrite"])
    db = SessionLocal()
    try:
        ep, model = _docs_ai(db)
        if not ep:
            raise HTTPException(400, "no model endpoint configured")
        if not model:
            raise HTTPException(400, "no model available")
        base_url, api_key = ep.base_url, ep.api_key
    finally:
        db.close()
    msgs = [
        {
            "role": "system",
            "content": sys_prompt
            + " Return ONLY the resulting text — no commentary, no code fences.",
        },
        {"role": "user", "content": text[:6000]},
    ]
    out = await simple_complete(msgs, base_url, api_key, model, max_tokens=600)
    out = (out or "").strip()
    out = out.removeprefix("```").removesuffix("```").strip()
    return {"text": out, "action": body.action}


class AiEditBody(BaseModel):
    path: str
    instruction: str


@router.post("/ai-edit")
async def ai_edit(body: AiEditBody):
    from core.database import SessionLocal
    from services.llm import stream_chat

    cur = vault_md.read(body.path)
    if not cur.get("exists"):
        raise HTTPException(404, "note not found")
    db = SessionLocal()
    try:
        ep, model = _docs_ai(db)
    finally:
        db.close()
    if not ep:
        raise HTTPException(400, "no endpoint configured")
    if not model:
        raise HTTPException(400, "no model available")

    msgs = [
        {
            "role": "system",
            "content": "You are a markdown note editor. Rewrite the note per the instruction. Keep any [[wikilinks]] intact unless asked to change them. Return ONLY the new note content — no commentary, no code fences.",
        },
        {"role": "user", "content": f"Instruction: {body.instruction}\n\nNote:\n{cur['content']}"},
    ]

    async def _gen():
        acc = []
        async for chunk in stream_chat(msgs, ep.base_url, ep.api_key, model):
            if "delta" in chunk:
                acc.append(chunk["delta"])
                yield f"data: {json.dumps({'delta': chunk['delta']})}\n\n"
            elif "thinking" in chunk:
                # reasoning models sit silent for ages before the rewrite starts —
                # heartbeat so the ui can show progress instead of looking dead
                yield 'data: {"thinking": 1}\n\n'
            elif "error" in chunk:
                yield f"data: {json.dumps(chunk)}\n\n"
        full = "".join(acc).strip()
        if full:
            vault_md.write(body.path, full)  # persist the rewrite
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )

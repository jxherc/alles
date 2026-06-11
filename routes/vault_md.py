import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from services import vault_md

router = APIRouter(prefix="/api/vault-md")


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


_REV_GAP = 300    # min seconds between automatic snapshots of the same doc
_REV_KEEP = 50    # revisions kept per doc


def _norm_path(rel: str) -> str:
    from pathlib import PurePosixPath
    rel = (rel or "").replace("\\", "/")
    return rel if PurePosixPath(rel).suffix else rel + ".md"


def _snapshot(rel: str, force: bool = False):
    """store the doc's current on-disk content as a revision (its pre-change
    state). autosave fires every keystroke pause, so unforced snapshots are
    rate-limited — you get the pre-session state plus one every ~5 minutes."""
    from datetime import datetime
    from core.database import SessionLocal, DocRevision
    rel = _norm_path(rel)
    try:
        cur = vault_md.read(rel)
    except ValueError:
        return
    if not cur.get("exists"):
        return
    db = SessionLocal()
    try:
        last = (db.query(DocRevision).filter_by(path=rel)
                .order_by(DocRevision.created_at.desc()).first())
        if last and last.content == cur["content"]:
            return
        if not force and last and (datetime.utcnow() - last.created_at).total_seconds() < _REV_GAP:
            return
        db.add(DocRevision(path=rel, content=cur["content"]))
        for old in (db.query(DocRevision).filter_by(path=rel)
                    .order_by(DocRevision.created_at.desc()).offset(_REV_KEEP).all()):
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
        pass   # automations must never break a save
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
        return vault_md.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RenameBody(BaseModel):
    path: str
    new_path: str


@router.post("/rename")
def rename_file(body: RenameBody):
    try:
        out = vault_md.rename(body.path, body.new_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # carry the history along with the doc
    from core.database import SessionLocal, DocRevision
    db = SessionLocal()
    try:
        db.query(DocRevision).filter_by(path=_norm_path(body.path)) \
          .update({"path": out.get("path", _norm_path(body.new_path))})
        db.commit()
    finally:
        db.close()
    return out


class ExtractTodosBody(BaseModel):
    path: str


@router.post("/extract-todos")
async def extract_todos(body: ExtractTodosBody):
    """AI-pull action items out of a doc and create real tasks from them."""
    import json as _json
    from core.database import SessionLocal, ModelEndpoint, Task
    from services.llm import simple_complete
    try:
        doc = vault_md.read(_norm_path(body.path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not doc.get("exists") or not (doc.get("content") or "").strip():
        raise HTTPException(404, "doc is empty or missing")

    db = SessionLocal()
    try:
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
        if not ep:
            raise HTTPException(400, "no model endpoint configured")
        model = ep.models_list()[0] if ep.models_list() else ""
        if not model:
            raise HTTPException(400, "no model available")
        prompt = [
            {"role": "system", "content": (
                "Extract actionable to-do items from the document. Reply with ONLY a JSON "
                "array of short task title strings, no prose, no code fences. If there is "
                "nothing actionable, reply []."
            )},
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


@router.get("/revisions")
def list_revisions(path: str):
    from core.database import SessionLocal, DocRevision
    db = SessionLocal()
    try:
        rows = (db.query(DocRevision).filter_by(path=_norm_path(path))
                .order_by(DocRevision.created_at.desc()).all())
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "size": len(r.content or "")}
                for r in rows]
    finally:
        db.close()


@router.get("/revisions/{rid}")
def get_revision(rid: str):
    from core.database import SessionLocal, DocRevision
    db = SessionLocal()
    try:
        r = db.get(DocRevision, rid)
        if not r:
            raise HTTPException(404)
        return {"id": r.id, "path": r.path, "content": r.content,
                "created_at": r.created_at.isoformat()}
    finally:
        db.close()


@router.post("/revisions/{rid}/restore")
def restore_revision(rid: str):
    from core.database import SessionLocal, DocRevision
    db = SessionLocal()
    try:
        r = db.get(DocRevision, rid)
        if not r:
            raise HTTPException(404)
        path, content = r.path, r.content
    finally:
        db.close()
    _snapshot(path, force=True)   # the state being replaced becomes a revision
    out = vault_md.write(path, content)
    return {"ok": True, "path": out.get("path", path)}


@router.get("/search")
def search(q: str = ""):
    return {"results": vault_md.search(q)}


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
def graph():
    return vault_md.graph()


class FolderBody(BaseModel):
    path: str


@router.post("/folder")
def make_folder(body: FolderBody):
    try:
        return vault_md.create_folder(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class AiEditBody(BaseModel):
    path: str
    instruction: str


@router.post("/ai-edit")
async def ai_edit(body: AiEditBody):
    from core.database import SessionLocal, ModelEndpoint
    from services.llm import stream_chat
    cur = vault_md.read(body.path)
    if not cur.get("exists"):
        raise HTTPException(404, "note not found")
    db = SessionLocal()
    try:
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    finally:
        db.close()
    if not ep:
        raise HTTPException(400, "no endpoint configured")
    model = ep.models_list()[0] if ep.models_list() else ""
    if not model:
        raise HTTPException(400, "no model available")

    msgs = [
        {"role": "system", "content": "You are a markdown note editor. Rewrite the note per the instruction. Keep any [[wikilinks]] intact unless asked to change them. Return ONLY the new note content — no commentary, no code fences."},
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
            vault_md.write(body.path, full)   # persist the rewrite
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

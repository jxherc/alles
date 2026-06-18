import json
from fastapi import APIRouter, HTTPException, UploadFile, File
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
    new_path = out.get("path", _norm_path(body.new_path))
    # carry the history along with the doc
    from core.database import SessionLocal, DocRevision

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


@router.get("/revisions")
def list_revisions(path: str):
    from core.database import SessionLocal, DocRevision

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
    from core.database import SessionLocal, DocRevision

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
    from core.database import SessionLocal, DocRevision

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
    from core.database import SessionLocal, DocRevision

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
        from core.database import SessionLocal, ModelEndpoint
        from services.llm import simple_complete

        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
            model = ep.models_list()[0] if ep and ep.models_list() else ""
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

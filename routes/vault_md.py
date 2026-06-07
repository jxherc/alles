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


@router.get("/file")
def read_file(path: str):
    try:
        return vault_md.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class WriteBody(BaseModel):
    path: str
    content: str = ""


@router.put("/file")
def write_file(body: WriteBody):
    try:
        return vault_md.write(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


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
        return vault_md.rename(body.path, body.new_path)
    except ValueError as e:
        raise HTTPException(400, str(e))


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
            elif "error" in chunk:
                yield f"data: {json.dumps(chunk)}\n\n"
        full = "".join(acc).strip()
        if full:
            vault_md.write(body.path, full)   # persist the rewrite
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

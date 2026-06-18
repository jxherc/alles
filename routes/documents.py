import json, asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Document

router = APIRouter(prefix="/api")


def _fmt(d: Document) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "doc_type": d.doc_type,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        "content_len": len(d.content),
    }


@router.get("/documents")
def list_docs(db: DbSession = Depends(get_db)):
    return [_fmt(d) for d in db.query(Document).order_by(Document.updated_at.desc()).all()]


class CreateDoc(BaseModel):
    title: str = "untitled"
    doc_type: str = "md"
    content: str = ""


@router.post("/documents")
def create_doc(body: CreateDoc, db: DbSession = Depends(get_db)):
    d = Document(title=body.title, doc_type=body.doc_type, content=body.content)
    db.add(d)
    db.commit()
    db.refresh(d)
    return {**_fmt(d), "content": d.content}


@router.get("/documents/{doc_id}")
def get_doc(doc_id: str, db: DbSession = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    return {**_fmt(d), "content": d.content}


class PatchDoc(BaseModel):
    title: str | None = None
    content: str | None = None
    doc_type: str | None = None


@router.patch("/documents/{doc_id}")
def patch_doc(doc_id: str, body: PatchDoc, db: DbSession = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    if body.title is not None:
        d.title = body.title
    if body.content is not None:
        d.content = body.content
    if body.doc_type is not None:
        d.doc_type = body.doc_type
    d.updated_at = datetime.utcnow()
    db.commit()
    return {**_fmt(d), "content": d.content}


@router.delete("/documents/{doc_id}")
def delete_doc(doc_id: str, db: DbSession = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    db.delete(d)
    db.commit()
    return {"ok": True}


class AiEditRequest(BaseModel):
    instruction: str


@router.post("/documents/{doc_id}/ai-edit")
async def ai_edit(doc_id: str, body: AiEditRequest, db: DbSession = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)

    from core.database import ModelEndpoint

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep:
        raise HTTPException(400, "no endpoint configured")
    model = ep.models_list()[0] if ep.models_list() else ""
    if not model:
        raise HTTPException(400, "no model available")

    from services.llm import stream_chat

    msgs = [
        {
            "role": "system",
            "content": "You are a document editor. Rewrite the document per the instruction. Return ONLY the new document content — no commentary, no markdown fences.",
        },
        {"role": "user", "content": f"Instruction: {body.instruction}\n\nDocument:\n{d.content}"},
    ]

    async def _gen():
        async for chunk in stream_chat(msgs, ep.base_url, ep.api_key, model):
            if "delta" in chunk:
                yield f"data: {json.dumps({'delta': chunk['delta']})}\n\n"
            elif "done" in chunk:
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        _gen(), media_type="text/event-stream", headers={"cache-control": "no-cache"}
    )

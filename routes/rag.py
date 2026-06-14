from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag")


@router.get("/status")
def status():
    from services import rag
    return {"indexed": len(rag._index) if rag._index is not None else 0,
            "built": rag._index is not None}


@router.post("/reindex")
def reindex():
    from services.rag import build_index
    return {"indexed": build_index()}


class AskBody(BaseModel):
    query: str


@router.post("/ask")
async def ask(body: AskBody):
    if not body.query.strip():
        raise HTTPException(400, "empty query")
    from core.database import SessionLocal, ModelEndpoint
    db = SessionLocal()
    try:
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
        if not ep or not ep.models_list():
            raise HTTPException(400, "no model endpoint configured")
        base, key, model = ep.base_url, ep.api_key, ep.models_list()[0]
    finally:
        db.close()
    from services.rag import answer
    return await answer(body.query, base, key, model)

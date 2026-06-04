"""
OpenAI-compatible API layer.
Model IDs: {endpoint_name}/{model}  e.g. "DeepSeek/deepseek-chat"
"""
import json, asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/v1")


def _db():
    from core.database import SessionLocal
    return SessionLocal()


@router.get("/models")
def list_models():
    db = _db()
    try:
        from core.database import ModelEndpoint
        eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
        data = []
        for ep in eps:
            for m in ep.models_list():
                data.append({
                    "id": f"{ep.name}/{m}",
                    "object": "model",
                    "owned_by": ep.name.lower(),
                    "created": 0,
                })
        return {"object": "list", "data": data}
    finally:
        db.close()


class OAIMessage(BaseModel):
    role: str
    content: str


class OAIRequest(BaseModel):
    model: str
    messages: list[OAIMessage]
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None


@router.post("/chat/completions")
async def chat_completions(body: OAIRequest):
    # resolve endpoint + model from "endpoint_name/model" format
    parts = body.model.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(400, "model must be 'EndpointName/model-id'")
    ep_name, model = parts

    db = _db()
    try:
        from core.database import ModelEndpoint
        ep = db.query(ModelEndpoint).filter(
            ModelEndpoint.name == ep_name, ModelEndpoint.enabled == True
        ).first()
        if not ep:
            raise HTTPException(404, f"endpoint '{ep_name}' not found")
        base_url, api_key = ep.base_url, ep.api_key
    finally:
        db.close()

    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    kw = {}
    if body.max_tokens: kw["max_tokens"] = body.max_tokens
    if body.temperature is not None: kw["temperature"] = body.temperature

    from services.llm import stream_chat

    if body.stream:
        async def _sse_gen():
            import time
            cid = f"chatcmpl-{int(time.time())}"
            async for chunk in stream_chat(msgs, base_url, api_key, model, **kw):
                if "delta" in chunk:
                    data = {
                        "id": cid, "object": "chat.completion.chunk",
                        "choices": [{"delta": {"content": chunk["delta"]}, "index": 0, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                elif "done" in chunk:
                    data = {
                        "id": cid, "object": "chat.completion.chunk",
                        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    }
                    yield f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n"
                    return
        return StreamingResponse(_sse_gen(), media_type="text/event-stream",
                                  headers={"cache-control": "no-cache"})
    else:
        acc = []
        async for chunk in stream_chat(msgs, base_url, api_key, model, **kw):
            if "delta" in chunk:
                acc.append(chunk["delta"])
        text = "".join(acc)
        import time
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": text},
                         "index": 0, "finish_reason": "stop"}],
        }

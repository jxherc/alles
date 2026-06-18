import json, uuid, asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api")

_COMPARE_DIR = Path(__file__).parent.parent / "data" / "compare"
_COMPARE_DIR.mkdir(parents=True, exist_ok=True)

# active compare tasks: compare_id → list of (endpoint, model, messages, stop_event)
_active: dict[str, list] = {}


class CompareModel(BaseModel):
    endpoint_id: str
    model: str


class CompareRequest(BaseModel):
    message: str
    models: list[CompareModel]
    system_prompt: str = ""


@router.post("/compare")
async def start_compare(body: CompareRequest):
    from core.database import SessionLocal, ModelEndpoint
    from services.llm import stream_chat
    from core.settings import load_settings

    if not body.models:
        raise HTTPException(400, "provide at least one model")

    compare_id = str(uuid.uuid4())
    settings = load_settings()
    sys_prompt = body.system_prompt or settings.get(
        "system_prompt", "You are aide, a helpful AI assistant."
    )

    db = SessionLocal()
    try:
        streams = []
        for m in body.models:
            ep = db.get(ModelEndpoint, m.endpoint_id)
            if not ep:
                continue
            msgs = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": body.message},
            ]
            stop = asyncio.Event()
            streams.append({"ep": ep, "model": m.model, "msgs": msgs, "stop": stop, "acc": []})
        _active[compare_id] = streams
    finally:
        db.close()

    return {"compare_id": compare_id, "count": len(_active[compare_id])}


@router.get("/compare/{compare_id}/stream/{idx}")
async def compare_stream(compare_id: str, idx: int):
    streams = _active.get(compare_id)
    if not streams or idx >= len(streams):
        raise HTTPException(404)

    entry = streams[idx]
    from services.llm import stream_chat

    async def _gen():
        async for chunk in stream_chat(
            entry["msgs"], entry["ep"].base_url, entry["ep"].api_key, entry["model"]
        ):
            if entry["stop"].is_set():
                break
            if "delta" in chunk:
                entry["acc"].append(chunk["delta"])
                yield f"data: {json.dumps(chunk)}\n\n"
            elif "done" in chunk:
                yield f"data: {json.dumps(chunk)}\n\n"
                break
            elif "error" in chunk:
                yield f"data: {json.dumps(chunk)}\n\n"
                break
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.delete("/compare/{compare_id}")
def stop_compare(compare_id: str):
    streams = _active.pop(compare_id, [])
    for s in streams:
        s["stop"].set()
    return {"ok": True}

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from core.settings import data_dir

router = APIRouter(prefix="/api")

_COMPARE_DIR: Path | None = None


def compare_dir() -> Path:
    d = _COMPARE_DIR or data_dir() / "compare"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    from core.database import ModelEndpoint, SessionLocal
    from core.settings import build_aide_system_prompt, load_settings

    if not body.models:
        raise HTTPException(400, "provide at least one model")

    compare_id = str(uuid.uuid4())
    settings = load_settings()
    sys_prompt = build_aide_system_prompt(settings, body.system_prompt)

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
    if (
        not streams or idx < 0 or idx >= len(streams)
    ):  # idx<0 would index from the end (wrong stream)
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


class VoteBody(BaseModel):
    winner: str
    loser: str = ""
    request_id: str = ""


@router.post("/compare/vote")
def record_vote(body: VoteBody):
    """record which model won a head-to-head — feeds the win-rate leaderboard."""
    from core.database import ModelVote, SessionLocal

    if not body.winner.strip():
        raise HTTPException(400, "winner required")
    identity = body.request_id
    if identity:
        try:
            if str(uuid.UUID(identity)) != identity:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "request_id must be a canonical UUID") from None
    winner, loser = body.winner.strip(), body.loser.strip()

    def replay(saved):
        if saved.winner != winner or saved.loser != loser:
            raise HTTPException(409, "this request already saved a different vote")
        return {"ok": True}

    db = SessionLocal()
    try:
        if identity and (saved := db.get(ModelVote, identity)) is not None:
            return replay(saved)
        values = {"winner": winner, "loser": loser}
        if identity:
            values["id"] = identity
        db.add(ModelVote(**values))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            saved = db.get(ModelVote, identity) if identity else None
            if saved is None:
                raise
            return replay(saved)
    finally:
        db.close()
    return {"ok": True}


@router.get("/compare/stats")
def compare_stats():
    """per-model wins/losses/win-rate, most-won first."""
    from core.database import ModelVote, SessionLocal

    db = SessionLocal()
    try:
        votes = db.query(ModelVote).all()
        tally: dict[str, dict] = {}
        for v in votes:
            tally.setdefault(v.winner, {"model": v.winner, "wins": 0, "losses": 0})["wins"] += 1
            if v.loser:
                tally.setdefault(v.loser, {"model": v.loser, "wins": 0, "losses": 0})["losses"] += 1
    finally:
        db.close()
    rows = []
    for r in tally.values():
        total = r["wins"] + r["losses"]
        r["total"] = total
        r["win_rate"] = round(r["wins"] / total, 3) if total else 0.0
        rows.append(r)
    rows.sort(key=lambda r: (-r["wins"], -r["win_rate"]))
    return {"votes": len(votes), "models": rows}

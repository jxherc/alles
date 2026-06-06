from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services.local_models import (
    PRESETS,
    download_model,
    get_job,
    hwfit,
    list_jobs,
    ollama_status,
    serve_model,
    start_ollama,
)

router = APIRouter(prefix="/api/local-models")


class ModelRequest(BaseModel):
    model: str


class ServeRequest(BaseModel):
    model: str
    autostart: bool = True
    set_default: bool = True


@router.get("/presets")
def presets():
    return {"presets": PRESETS}


@router.get("/status")
async def status():
    fit = await hwfit()
    return {
        "ollama": await ollama_status(),
        "hardware": fit["hardware"],
        "presets": fit["presets"],
    }


@router.get("/hwfit")
async def hardware_fit():
    return await hwfit()


@router.post("/start")
def start():
    return start_ollama()


@router.post("/download_model")
def download(body: ModelRequest):
    try:
        return download_model(body.model)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = get_job(job_id)
    if not found:
        raise HTTPException(404, "job not found")
    return found


@router.get("/jobs")
def jobs():
    return {"jobs": list_jobs()}


@router.post("/serve")
async def serve(body: ServeRequest, db: DbSession = Depends(get_db)):
    try:
        result = await serve_model(body.model, db, body.autostart, body.set_default)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not result.get("ok"):
        raise HTTPException(409, result)
    return result

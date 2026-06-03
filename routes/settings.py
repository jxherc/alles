from fastapi import APIRouter
from pydantic import BaseModel
from core.settings import load_settings, save_settings

router = APIRouter(prefix="/api")


@router.get("/settings")
def get_settings():
    return load_settings()


class SettingsPatch(BaseModel):
    default_model: str | None = None
    default_endpoint_id: str | None = None
    system_prompt: str | None = None
    stream_thinking: bool | None = None


@router.patch("/settings")
def patch_settings(body: SettingsPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return save_settings(patch)

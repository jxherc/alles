from fastapi import APIRouter
from pydantic import BaseModel
from core.settings import load_settings, save_settings

router = APIRouter(prefix="/api")


_STRIP = {"auth_password_hash", "vault_verifier", "vault_pw_b64"}

@router.get("/settings")
def get_settings():
    s = load_settings()
    return {k: v for k, v in s.items() if k not in _STRIP}


class SettingsPatch(BaseModel):
    default_model: str | None = None
    default_endpoint_id: str | None = None
    system_prompt: str | None = None
    context_limit: int | None = None
    stream_thinking: bool | None = None
    artifacts_enabled: bool | None = None
    auto_compact: bool | None = None
    compact_threshold: int | None = None
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    openai_api_key: str | None = None
    search_provider: str | None = None
    search_result_count: int | None = None
    tavily_api_key: str | None = None


@router.patch("/settings")
def patch_settings(body: SettingsPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return save_settings(patch)

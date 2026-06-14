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
    agent_max_turns: int | None = None
    agent_max_tokens: int | None = None
    agent_permission_mode: str | None = None
    agent_allowed_roots: list[str] | None = None
    auto_compact: bool | None = None
    compact_threshold: int | None = None
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    openai_api_key: str | None = None
    search_provider: str | None = None
    search_result_count: int | None = None
    search_fallback_chain: list[str] | None = None
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    searxng_url: str | None = None
    google_pse_api_key: str | None = None
    google_pse_cx: str | None = None
    serper_api_key: str | None = None
    search_fallback: str | None = None
    memory_auto_inject: bool | None = None
    tts_speed: float | None = None
    tts_auto_play: bool | None = None
    stt_language: str | None = None
    theme: str | None = None      # '' (dark/default) | 'light' — synced across subdomains
    accent: str | None = None     # hex like '#818cf8', or '' for the default
    notify_discord_webhook: str | None = None
    notify_telegram_token: str | None = None
    notify_telegram_chat_id: str | None = None
    notify_on_agent_done: bool | None = None


@router.patch("/settings")
def patch_settings(body: SettingsPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return save_settings(patch)

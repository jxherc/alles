import os, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")  # utf-8-sig handles windows BOM

_SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"

_defaults = {
    "default_model": "",
    "default_endpoint_id": "",
    "system_prompt": "You are aide, a helpful personal AI assistant.",
    "context_limit": 40,
    "stream_thinking": True,
    "artifacts_enabled": True,
    "agent_max_turns": 24,
    "agent_max_tokens": 0,
    "agent_permission_mode": "full_auto",
    "agent_allowed_roots": [],
    "agent_context_files": True,        # read AGENTS.md from working dir
    "agent_sandbox": False,             # run shell inside docker
    "agent_sandbox_image": "alpine:latest",
    "agent_sandbox_no_net": False,      # --network none in sandbox
    "agent_computer_use": False,        # enable screenshot/click/type tools
    "agent_subagents": True,            # allow spawn_agent delegation
    "auto_compact": True,
    "compact_threshold": 30,
    "stt_provider": "browser",    # browser | local | whisper_api
    "stt_model": "base",          # faster-whisper size for local: tiny|base|small|medium|large-v3
    "tts_provider": "browser",    # openai | browser
    "tts_voice": "alloy",
    "openai_api_key": "",         # for TTS/STT
    "search_provider": "duckduckgo",
    "search_result_count": 5,
    "search_fallback_chain": ["duckduckgo"],
    "tavily_api_key": "",
    "brave_api_key": "",
    "searxng_url": "",
    "google_pse_api_key": "",
    "google_pse_cx": "",
    "serper_api_key": "",
    "search_fallback": "duckduckgo",
    "memory_auto_inject": True,
    "tts_speed": 1.0,
    "tts_auto_play": False,
    "stt_language": "",
}

_ARTIFACT_INSTRUCTIONS = (
    "When producing any complete, renderable output — an HTML page or component, "
    "an SVG graphic, a runnable code snippet, or a formatted markdown document — "
    "wrap it in an artifact tag instead of a bare code block:\n\n"
    "<aide-artifact type=\"html|svg|code|markdown\" title=\"short title\" lang=\"python\">\n"
    "...content...\n"
    "</aide-artifact>\n\n"
    "Types:\n"
    "- html: full HTML pages/components\n"
    "- svg: SVG graphics\n"
    "- code: runnable code (set lang= to the language, e.g. lang=\"python\")\n"
    "- markdown: formatted documents\n\n"
    "Only wrap complete, self-contained outputs — not fragments or inline examples. "
    "You may still write brief explanatory text before the artifact."
)

def load_settings() -> dict:
    s = dict(_defaults)
    if _SETTINGS_FILE.exists():
        try:
            s.update(json.loads(_SETTINGS_FILE.read_text("utf-8")))
        except Exception:
            pass
    return s

def save_settings(patch: dict):
    s = load_settings()
    s.update(patch)
    # never persist the vault password — strip it if it snuck in
    s.pop("vault_pw_b64", None)
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(s, indent=2), "utf-8")
    return s

# env helpers
def get_secret_key() -> str:
    return os.getenv("SECRET_KEY", "dev-secret-change-me")

def auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

def get_port() -> int:
    return int(os.getenv("PORT", "8000"))

def deepseek_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "")

def anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")

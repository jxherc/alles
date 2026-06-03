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
}

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

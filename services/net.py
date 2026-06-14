"""
outbound networking helpers. honors an optional `outbound_proxy` setting so all
httpx-based calls (LLM, research, notifications, web push) route through a proxy
— handy behind a corporate/GFW network where direct egress is blocked. httpx
picks up HTTP(S)_PROXY from the environment automatically, so applying the
setting to the env is all it takes.
"""
import os


def apply_proxy() -> str:
    """read the configured proxy and export it to the env. returns the proxy
    url (or '' if none). safe to call repeatedly; empty setting clears nothing
    the user set themselves via the real env before launch."""
    try:
        from core.settings import load_settings
        proxy = (load_settings().get("outbound_proxy") or "").strip()
    except Exception:
        proxy = ""
    if proxy:
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["HTTP_PROXY"] = proxy
    return proxy

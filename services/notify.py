"""
push a short notification out to Discord and/or Telegram — used to ping when a
long agent run finishes or needs approval, so you don't have to babysit the tab.

config lives in settings (set in the app, no file editing):
  notify_discord_webhook   - a Discord channel webhook url
  notify_telegram_token    - a Telegram bot token
  notify_telegram_chat_id  - the chat id to message
all optional; if nothing's set, send() is a no-op.
"""

import logging
import httpx

log = logging.getLogger("aide.notify")


def _targets() -> dict:
    from core.settings import load_settings

    s = load_settings()
    return {
        "discord": s.get("notify_discord_webhook", "").strip(),
        "tg_token": s.get("notify_telegram_token", "").strip(),
        "tg_chat": str(s.get("notify_telegram_chat_id", "")).strip(),
    }


def configured() -> bool:
    t = _targets()
    return bool(t["discord"] or (t["tg_token"] and t["tg_chat"]))


async def send(text: str) -> dict:
    """fire to every configured channel. returns which ones were attempted/ok.
    never raises — a notification failure must not break the thing that triggered it."""
    t = _targets()
    out = {"discord": None, "telegram": None}
    if not text:
        return out
    async with httpx.AsyncClient(timeout=8.0) as c:
        if t["discord"]:
            try:
                r = await c.post(t["discord"], json={"content": text[:1900]})
                out["discord"] = r.status_code < 300
            except Exception as e:
                log.warning(f"discord notify failed: {e}")
                out["discord"] = False
        if t["tg_token"] and t["tg_chat"]:
            try:
                r = await c.post(
                    f"https://api.telegram.org/bot{t['tg_token']}/sendMessage",
                    json={"chat_id": t["tg_chat"], "text": text[:4000]},
                )
                out["telegram"] = r.status_code < 300
            except Exception as e:
                log.warning(f"telegram notify failed: {e}")
                out["telegram"] = False
    return out

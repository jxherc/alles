"""text Aide on Telegram through your own bot.

alles long-polls the bot (no public address needed) and answers only the owner's private chat,
the same chat id telegram notifications go to. telegram's servers carry the messages, so
approvals stay inside alles (see services/channel_runs.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time

import httpx

from services import channel_runs

log = logging.getLogger("alles.telegram")

API = "https://api.telegram.org"
POLL_SECONDS = 2.0
LONG_POLL = 30
# telegram keeps unread updates for a day; a message older than this waited out an outage and
# would get a confusing late answer
STALE_SECONDS = 15 * 60
TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{20,}")

state = {"state": "off", "error": "", "handled": 0, "ignored": 0, "bot": ""}
_runs: dict[str, dict] = {}
_seen: list[str] = []
_told_text_only: dict[str, float] = {}
_typing_at: dict[str, float] = {}
_client: httpx.AsyncClient | None = None
_poller: asyncio.Task | None = None


class TelegramError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def settings() -> dict:
    from core.settings import load_settings

    s = load_settings()
    return {
        "enabled": bool(s.get("telegram_chat_enabled")),
        "token": str(s.get("notify_telegram_token") or "").strip(),
        "chat_id": str(s.get("notify_telegram_chat_id") or "").strip(),
    }


def public() -> dict:
    current = settings()
    return {
        "enabled": current["enabled"],
        "has_token": bool(current["token"]),
        "has_chat": bool(current["chat_id"]),
        "state": state["state"] if current["enabled"] else "off",
        "error": state["error"],
        "bot": state["bot"],
        "handled": state["handled"],
        "ignored": state["ignored"],
    }


def find_chat(token: str) -> dict:
    """the newest private chat that messaged the bot, so nobody has to dig for a chat id."""
    if not TOKEN_RE.fullmatch(token):
        raise TelegramError(
            400, "telegram_token_missing", "paste the bot token from BotFather first"
        )
    try:
        response = httpx.get(f"{API}/bot{token}/getUpdates", timeout=10)
        data = response.json()
    except Exception as exc:
        raise TelegramError(
            502, "telegram_unreachable", "could not reach telegram, try again"
        ) from exc
    if response.status_code in (401, 404):
        raise TelegramError(400, "telegram_token_invalid", "telegram did not accept that bot token")
    updates = data.get("result") if isinstance(data, dict) else None
    for update in reversed(updates if isinstance(updates, list) else []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id") is not None:
            name = chat.get("first_name") or chat.get("username") or ""
            return {"chat_id": str(chat["id"]), "name": str(name)[:100]}
    raise TelegramError(
        404, "telegram_no_message", "send your bot any message in telegram, then try again"
    )


async def _call(method: str, timeout: float = 15, **params) -> dict:
    global _client
    token = settings()["token"]
    if _client is None:
        _client = httpx.AsyncClient()
    response = await _client.post(f"{API}/bot{token}/{method}", json=params, timeout=timeout)
    data = response.json()
    if not data.get("ok"):
        raise TelegramError(
            response.status_code, "telegram_error", str(data.get("description"))[:300]
        )
    return data.get("result")


async def reply(space: str, text: str) -> None:
    # telegram caps a message at 4096 characters
    for start in range(0, len(text), 4000):
        await _call("sendMessage", chat_id=space, text=text[start : start + 4000])


async def _typing(space: str, on: bool) -> None:
    # telegram's typing status ends by itself after ~5 seconds or at the next message
    if on:
        _typing_at[space] = time.monotonic()
        with contextlib.suppress(Exception):
            await _call("sendChatAction", chat_id=space, action="typing")
    else:
        _typing_at.pop(space, None)


async def handle_update(update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    space = str(chat.get("id") or "")
    message_id = f"{space}:{message.get('message_id')}"
    if not space or message_id in _seen:
        return
    _seen.append(message_id)
    del _seen[:-500]
    if chat.get("type") != "private" or space != settings()["chat_id"]:
        # anyone can find a bot by name; only the owner's chat gets answers
        state["ignored"] += 1
        return
    if time.time() - float(message.get("date") or 0) > STALE_SECONDS:
        return
    text = str(message.get("text") or "").strip()
    if not text:
        if time.monotonic() - _told_text_only.get(space, float("-inf")) >= 60:
            _told_text_only[space] = time.monotonic()
            await reply(space, "I can only read text here for now.")
        return
    state["handled"] += 1
    if await channel_runs.maybe_answer(_runs, space, text, reply):
        return
    from services import jarvis_handoff

    run_id = channel_runs.start_work("telegram", space, message_id, text)
    _runs[run_id] = {"space": space, "told": set()}
    await _typing(space, True)
    jarvis_handoff.launch(run_id)


async def _watch_runs() -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if not _runs:
            continue
        await channel_runs.watch_once(_runs, reply, _typing, log)
        # keep "typing..." up while Aide works
        for space in {info["space"] for info in _runs.values()}:
            if space in _typing_at and time.monotonic() - _typing_at[space] > 4:
                await _typing(space, True)


async def _poll() -> None:
    offset = None
    me = await _call("getMe")
    state.update(state="ready", error="", bot=str(me.get("username") or ""))
    while True:
        current = settings()
        if not (current["enabled"] and current["token"] and current["chat_id"]):
            return
        params = {"timeout": LONG_POLL, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        updates = await _call("getUpdates", timeout=LONG_POLL + 10, **params)
        for update in updates or []:
            offset = int(update["update_id"]) + 1
            try:
                await handle_update(update)
            except Exception as exc:
                log.warning("telegram message failed: %s", type(exc).__name__)


async def run_forever() -> None:
    """poll while telegram chat is turned on, retrying with a growing pause."""
    global _poller
    watcher = asyncio.create_task(_watch_runs())
    pause = 5
    try:
        while True:
            current = settings()
            if not (current["enabled"] and current["token"] and current["chat_id"]):
                state.update(state="off", error="")
                await asyncio.sleep(10)
                continue
            started = time.monotonic()
            _poller = asyncio.create_task(_poll())
            await asyncio.wait({_poller})
            if _poller.cancelled():  # restart(): go again with the new settings
                pause = 5
                continue
            exc = _poller.exception()
            if exc is None:
                continue
            state.update(
                state="error",
                error=exc.message if isinstance(exc, TelegramError) else type(exc).__name__,
            )
            if time.monotonic() - started > 120:
                pause = 5
            await asyncio.sleep(pause)
            pause = min(pause * 2, 300)
    finally:
        watcher.cancel()
        if _poller is not None:
            _poller.cancel()


async def restart() -> None:
    """after a settings change: drop the open long poll so the loop picks up the new values."""
    if _poller is not None and not _poller.done():
        _poller.cancel()

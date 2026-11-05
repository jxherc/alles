"""text Aide over iMessage through Photon's cloud line (spectrum-ts).

a small node helper keeps photon's connection open; alles reads one json line per message. only
the owner's own handles are answered. a text goes into Aide's main conversation as background
work; the reply comes back as a text. questions with choices can be answered by replying;
approvals for risky actions stay inside alles, because photon's servers relay every message and
a relay must not be able to say yes for the owner.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import time
from pathlib import Path

from services import channel_runs

log = logging.getLogger("alles.photon")

SPECTRUM_VERSION = "12.11.0"
SIDECAR = Path(__file__).parent / "photon" / "sidecar.mjs"
POLL_SECONDS = 2.0
NOT_TEXT = {
    "attachment",
    "voice",
    "contact",
    "poll",
}  # things a person sent that alles cannot read yet

state = {
    "state": "off",
    "error": "",
    "ignored": 0,
    "last_ignored": "",
    "handled": 0,
    # owner number -> the Photon line it texts; filled when the line connects
    "lines": {},
    "register_error": "",
    # why the last notification text did not go out: "" | "text_first" | "failed"
    "notify_note": "",
}
_proc = None
_task: asyncio.Task | None = None
_install: asyncio.Task | None = None
_seen: list[str] = []
# run id -> {"space", "told": set of notices already sent}
_runs: dict[str, dict] = {}
_told_text_only: dict[str, float] = {}
# send id -> future of the sidecar's {"type":"sent"} or {"type":"error"} answer
_pending: dict[str, asyncio.Future] = {}
DELIVER_TIMEOUT = 20.0


def _home() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "alles" / f"photon-{SPECTRUM_VERSION}"


def settings() -> dict:
    from core.settings import load_settings

    saved = load_settings()
    handles = saved.get("photon_owner_handles") or []
    return {
        "enabled": bool(saved.get("photon_enabled")),
        "project_id": str(saved.get("photon_project_id") or ""),
        "has_secret": bool(saved.get("photon_project_secret")),
        "owner_handles": [str(h) for h in handles if str(h).strip()],
        "read_receipts": saved.get("photon_read_receipts", True) is not False,
    }


def _normal(handle: str) -> str:
    handle = (handle or "").strip().lower()
    digits = "".join(c for c in handle if c.isdigit())
    return handle if "@" in handle else (digits[-10:] if len(digits) >= 10 else handle)


def is_owner(sender: str, handles: list[str]) -> bool:
    who = _normal(sender)
    return bool(who) and any(_normal(h) == who for h in handles)


def installed() -> bool:
    return (_home() / "node_modules" / "spectrum-ts" / "package.json").exists()


def public() -> dict:
    from services import photon_setup

    current = settings()
    return {
        **current,
        **state,
        "installed": installed(),
        "has_secret": current["has_secret"],
        "login": photon_setup.public_login(),
    }


async def register_numbers() -> None:
    """make sure Photon lets the owner's numbers through (the shared line only passes texts
    from the project's registered users), and learn which line each one texts."""
    from core.settings import load_settings
    from services import photon_setup

    saved = load_settings()
    try:
        numbers = await photon_setup.ensure_numbers(
            str(saved.get("photon_project_id") or ""),
            str(saved.get("photon_project_secret") or ""),
            [str(h) for h in saved.get("photon_owner_handles") or []],
        )
        state.update(lines=numbers["lines"], register_error=numbers["error"])
        if numbers["added"]:
            log.info("photon: registered %d owner number(s)", len(numbers["added"]))
    except Exception as exc:
        state["register_error"] = str(exc)[:300]


async def _run_install() -> None:
    from core.tool_path import find_tool

    npm = find_tool("npm")
    if not npm:
        raise RuntimeError("npm was not found on this machine")
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        npm,
        "install",
        "--prefix",
        str(home),
        "--no-audit",
        "--no-fund",
        "--ignore-scripts",
        f"spectrum-ts@{SPECTRUM_VERSION}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=600)
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or ["npm failed"]
        raise RuntimeError(tail[0][:300])


# ── the connection ──


async def _send(command: dict) -> None:
    if _proc is None or _proc.returncode is not None:
        return
    _proc.stdin.write((json.dumps(command) + "\n").encode())
    await _proc.stdin.drain()


async def reply(space: str, text: str) -> None:
    await _send({"type": "send", "space": space, "text": text})


def _is_dm(space: str) -> bool:
    # Photon names a one-to-one chat `any;-;<number>` and a group `any;+;<guid>`
    # (hermes plugins/platforms/photon/sidecar/index.mjs:93); a bare number is a DM too
    return not space.startswith("any;+;")


def _owner_target() -> str:
    """where a notification goes: the owner's last DM (kept in settings so a restart keeps it),
    else a bare phone number of theirs, which the sidecar turns into a DM like hermes does for
    PHOTON_HOME_CHANNEL (adapter.py:333, sidecar/index.mjs:962). never anyone else."""
    from core.settings import load_settings

    saved = load_settings()
    handles = settings()["owner_handles"]
    space, who = str(saved.get("photon_owner_space") or ""), str(saved.get("photon_owner_by") or "")
    if space and is_owner(who, handles):  # the number it came from is still one of theirs
        return space
    for handle in handles:
        digits = "".join(c for c in handle if c.isdigit())
        if "@" not in handle and len(digits) >= 10:
            return "+" + digits
    return ""


def can_notify() -> bool:
    current = settings()
    return bool(
        current["enabled"]
        and current["project_id"]
        and current["has_secret"]
        and current["owner_handles"]
    )


async def deliver(text: str) -> bool:
    """text the owner in their own DM. returns whether Photon took it. a refusal (shared and free
    lines may only reply to a chat the owner started: adapter.py:85 "Target not allowed") leaves
    a one line note for the settings screen instead of failing silently."""
    if not text or not can_notify():
        return False
    if _proc is None or _proc.returncode is not None or state["state"] != "ready":
        log.warning("photon: notification not sent, the line is %s", state["state"])
        state["notify_note"] = "failed"
        return False
    target = _owner_target()
    if not target:
        state["notify_note"] = "text_first"
        log.warning("photon: no conversation with the owner yet; text alles once from your phone")
        return False
    send_id = f"n{time.monotonic_ns()}"
    waiter = asyncio.get_running_loop().create_future()
    _pending[send_id] = waiter
    try:
        await _send({"type": "send", "space": target, "text": text, "id": send_id, "resolve": True})
        answer = await asyncio.wait_for(waiter, DELIVER_TIMEOUT)
    except TimeoutError:
        state["notify_note"] = "failed"
        log.warning("photon: notification timed out")
        return False
    finally:
        _pending.pop(send_id, None)
    if answer.get("type") == "sent":
        state["notify_note"] = ""
        return True
    refused = answer.get("class") == "target_not_allowed" or "resolve space" in str(
        answer.get("message") or ""
    )
    state["notify_note"] = "text_first" if refused else "failed"
    log.warning("photon: notification refused (%s)", "text first" if refused else "error")
    return False


def _remember_dm(space: str, sender: str) -> None:
    from core.settings import load_settings, save_settings

    if not space or not _is_dm(space):
        return
    saved = load_settings()
    if saved.get("photon_owner_space") != space or saved.get("photon_owner_by") != sender:
        save_settings({"photon_owner_space": space, "photon_owner_by": sender})
    state["notify_note"] = ""


async def _typing(space: str, on: bool) -> None:
    await _send({"type": "typing", "space": space, "on": on})


# imessage's bubble lapses after ~5s (hermes gateway/platforms/base.py:3350). hermes ticks every 2s
# and drops a send within 5s of the last (plugins/platforms/photon/adapter.py:81), which with 2s
# ticks means a gap of 6s, longer than the bubble lives. so the shortest gap here is 4s: sends go
# out at 0, 4, 8... seconds, still one signal per chat every few seconds.
_presence = channel_runs.Presence(lambda space, on: _typing(space, on), every=4.0)


async def _mark_read(space: str, message_id: str) -> None:
    # hermes marks every inbound message read once it has reached the agent (sidecar/index.mjs:619-640)
    # and lets PHOTON_READ_RECEIPTS=false turn that off; here the setting is `photon_read_receipts`
    if settings()["read_receipts"]:
        await _send({"type": "read", "space": space, "id": message_id})


async def _connect() -> None:
    global _proc
    from core.settings import load_settings

    saved = load_settings()
    if not installed():
        state.update(state="installing", error="")
        await _run_install()
    home = _home()
    shutil.copyfile(SIDECAR, home / "sidecar.mjs")  # node finds spectrum-ts next to it
    from core.tool_path import find_tool

    node = find_tool("node")
    if not node:
        raise RuntimeError("node was not found on this machine")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALLES_")}
    env.update(
        PHOTON_PROJECT_ID=str(saved.get("photon_project_id") or ""),
        PHOTON_PROJECT_SECRET=str(saved.get("photon_project_secret") or ""),
    )
    state.update(state="connecting", error="")
    _proc = await asyncio.create_subprocess_exec(
        node,
        str(home / "sidecar.mjs"),
        cwd=str(home),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=8 * 1024 * 1024,
    )
    watcher = asyncio.create_task(_watch_runs())
    try:
        while line := await _proc.stdout.readline():
            with contextlib.suppress(ValueError):
                await _handle(json.loads(line))
    finally:
        watcher.cancel()
    code = await _proc.wait()
    if state["state"] != "error":
        state.update(state="error", error=f"the photon helper stopped (exit {code})")


async def _handle(record: dict) -> None:
    kind = record.get("type")
    if kind == "ready":
        state.update(state="ready", error="")
    elif kind in ("sent", "error") and str(record.get("id") or "") in _pending:
        waiter = _pending[str(record["id"])]
        if not waiter.done():
            waiter.set_result(record)
    elif kind == "error":
        state["error"] = str(record.get("message") or "")[:300]
        if "refused" in state["error"] or "not installed" in state["error"]:
            state["state"] = "error"
    elif kind == "message":
        await handle_message(record)


async def handle_message(record: dict) -> None:
    message_id = str(record.get("id") or "")
    if not message_id or message_id in _seen:
        return
    _seen.append(message_id)
    del _seen[:-500]
    text = str(record.get("text") or "").strip()
    sender, space = str(record.get("sender") or ""), str(record.get("space") or "")
    if not is_owner(sender, settings()["owner_handles"]):
        # the shared photon line can be texted by anyone; only the owner is answered
        state["ignored"] += 1
        state["last_ignored"] = sender[:80]
        return
    _remember_dm(space, sender)
    if not text:
        # a photo or voice note gets one heads-up a minute; typing bubbles, reactions and the
        # like get nothing, or every bubble would answer itself
        if (
            record.get("kind") in NOT_TEXT
            and time.monotonic() - _told_text_only.get(space, float("-inf")) >= 60
        ):
            _told_text_only[space] = time.monotonic()
            await reply(space, "I can only read text here for now.")
        return
    state["handled"] += 1
    await _mark_read(space, message_id)
    if await _maybe_answer(space, text):
        return
    from services import jarvis_handoff

    run_id = channel_runs.start_work("photon", space, message_id, text)
    _runs[run_id] = {"space": space, "told": set()}
    await _presence(space, True)
    jarvis_handoff.launch(run_id)


async def _maybe_answer(space: str, text: str) -> bool:
    return await channel_runs.maybe_answer(_runs, space, text, reply)


async def _watch_runs() -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if _runs:
            await channel_runs.watch_once(_runs, reply, _presence, log)
            await _presence.tick(_runs)


async def run_forever() -> None:
    """keep the line open while photon is turned on, retrying with a growing pause."""
    pause = 5
    while True:
        current = settings()
        if not (current["enabled"] and current["project_id"] and current["has_secret"]):
            state.update(state="off")
            await asyncio.sleep(10)
            continue
        started = time.monotonic()
        try:
            await register_numbers()
            await _connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.update(state="error", error=str(exc)[:300])
        if time.monotonic() - started > 120:
            pause = 5
        await asyncio.sleep(pause)
        pause = min(pause * 2, 300)


async def restart() -> None:
    """after a settings change: drop the line so run_forever reconnects with the new values."""
    if _proc is not None and _proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            _proc.terminate()


async def stop() -> None:
    if _task is not None:
        _task.cancel()
    await restart()

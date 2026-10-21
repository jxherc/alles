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

log = logging.getLogger("alles.photon")

SPECTRUM_VERSION = "12.11.0"
SIDECAR = Path(__file__).parent / "photon" / "sidecar.mjs"
POLL_SECONDS = 2.0
DONE = {"succeeded", "failed", "cancelled", "interrupted", "uncertain"}

state = {
    "state": "off",
    "error": "",
    "ignored": 0,
    "last_ignored": "",
    "handled": 0,
    # owner number -> the Photon line it texts; filled when the line connects
    "lines": {},
    "register_error": "",
}
_proc = None
_task: asyncio.Task | None = None
_install: asyncio.Task | None = None
_seen: list[str] = []
# run id -> {"space", "told": set of notices already sent}
_runs: dict[str, dict] = {}


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
    npm = shutil.which("npm")
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


async def _typing(space: str, on: bool) -> None:
    await _send({"type": "typing", "space": space, "on": on})


async def _connect() -> None:
    global _proc
    from core.settings import load_settings

    saved = load_settings()
    if not installed():
        state.update(state="installing", error="")
        await _run_install()
    home = _home()
    shutil.copyfile(SIDECAR, home / "sidecar.mjs")  # node finds spectrum-ts next to it
    node = shutil.which("node")
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
    if not text:
        await reply(space, "I can only read text here for now.")
        return
    state["handled"] += 1
    if await _maybe_answer(space, text):
        return
    from core.database import SessionLocal
    from services import jarvis_handoff
    from services.aide_conversation import get_or_create_primary

    db = SessionLocal()
    try:
        session = get_or_create_primary(db)
        run = jarvis_handoff.create_handoff(
            db,
            session,
            text,
            permission_mode="approve",
            effort="medium",
            origin={"kind": "photon", "channel_id": space, "message_id": message_id},
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()
    _runs[run_id] = {"space": space, "told": set()}
    await _typing(space, True)
    jarvis_handoff.launch(run_id)


async def _maybe_answer(space: str, text: str) -> bool:
    """a reply to the question Aide just asked here answers it."""
    from core.database import JarvisRunPrompt, SessionLocal
    from services import jarvis_handoff
    from services.jarvis_store import answer_choice, json_value

    ours = [run_id for run_id, info in _runs.items() if info["space"] == space]
    if not ours:
        return False
    db = SessionLocal()
    try:
        prompt = (
            db.query(JarvisRunPrompt)
            .filter(
                JarvisRunPrompt.run_id.in_(ours),
                JarvisRunPrompt.state == "pending",
                JarvisRunPrompt.kind == "choice",  # approvals never get answered over text
            )
            .order_by(JarvisRunPrompt.created_at.desc())
            .first()
        )
        if prompt is None or json_value(prompt.question_schema, dict):
            return False
        options = [str(o) for o in json_value(prompt.options, list)]
        picked = next((o for o in options if o.lower() == text.lower()), None)
        if picked is None and text.isdigit() and 0 < int(text) <= len(options):
            picked = options[int(text) - 1]
        if picked is None:
            return False
        answer_choice(db, prompt, picked)
        db.commit()
        prompt_id, run_id = prompt.id, prompt.run_id
    finally:
        db.close()
    from services.agent_runtime import resolve_user_question_from_jarvis

    if not resolve_user_question_from_jarvis(prompt_id, {}):
        jarvis_handoff.launch(run_id)
    await reply(space, f"got it: {picked}")
    return True


async def _watch_runs() -> None:
    """send each run's answer when it ends, and its questions while it waits."""
    from core.database import DelegatedAction, JarvisRun, JarvisRunPrompt, SessionLocal
    from services.jarvis_store import json_value

    while True:
        await asyncio.sleep(POLL_SECONDS)
        if not _runs:
            continue
        db = SessionLocal()
        try:
            for run_id, info in list(_runs.items()):
                run = db.get(JarvisRun, run_id)
                if run is None:
                    _runs.pop(run_id, None)
                    continue
                for prompt in (
                    db.query(JarvisRunPrompt).filter_by(run_id=run_id, state="pending").all()
                ):
                    if prompt.id in info["told"]:
                        continue
                    info["told"].add(prompt.id)
                    if prompt.kind == "choice":
                        options = [str(o) for o in json_value(prompt.options, list)]
                        listed = "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1))
                        await _typing(info["space"], False)
                        await reply(
                            info["space"],
                            f"{prompt.question}\n{listed}\nreply with a number or the option.",
                        )
                    else:
                        await _typing(info["space"], False)
                        await reply(
                            info["space"],
                            f"this needs your ok in Aide: {prompt.action or prompt.question}. "
                            "approvals only happen inside alles, not over text.",
                        )
                # tool approvals (shell, file writes...) wait on the conversation, not as a run
                # prompt, so look for them by the run's conversation too
                for action in (
                    db.query(DelegatedAction)
                    .filter(
                        DelegatedAction.session_id == run.session_id,
                        DelegatedAction.state == "pending",
                        DelegatedAction.created_at >= run.created_at,
                    )
                    .all()
                ):
                    if action.id in info["told"]:
                        continue
                    info["told"].add(action.id)
                    await _typing(info["space"], False)
                    await reply(
                        info["space"],
                        f"this needs your ok in Aide: {action.action}. "
                        "approvals only happen inside alles, not over text.",
                    )
                if run.state in DONE:
                    await _typing(info["space"], False)
                    text = (run.result_summary or "").strip() if run.state == "succeeded" else ""
                    if not text:
                        text = {
                            "failed": f"that didn't work: {run.safe_error or 'Aide could not finish'}",
                            "cancelled": "stopped.",
                        }.get(run.state, "I lost track of that one; check Aide.")
                    await reply(info["space"], text[:6000])
                    _runs.pop(run_id, None)
        except Exception as exc:
            log.warning("photon run watch failed: %s", type(exc).__name__)
        finally:
            db.close()


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

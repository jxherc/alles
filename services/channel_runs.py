"""what every "text Aide from a chat app" channel shares.

a message becomes background work in Aide's main conversation. a question with choices goes back
as a numbered list and a reply answers it. approvals stay inside alles, because the chat app's
servers relay every message and a relay must not be able to say yes for the owner. the answer is
sent when the run ends.

each channel keeps its own `runs` dict (run id -> {"space", "told"}) and passes its own `reply`
and `typing` coroutines. a channel wraps its typing coroutine in one `Presence`, so "typing..."
shows at once, is sent again before the chat app lets it lapse, stops on the answer or an error,
and stays off while a question waits for the owner.
"""

from __future__ import annotations

import contextlib
import logging
import time

DONE = {"succeeded", "failed", "cancelled", "interrupted", "uncertain"}


class Presence:
    """the "typing..." bubble for one channel, copied from hermes (v0.22.2+canary 20acba0).

    hermes's `_keep_typing` (gateway/platforms/base.py:3350) calls `send_typing` every 2s because
    a chat app's bubble lapses after about 5s, skips a chat while an approval waits
    (`_typing_paused`), and its photon adapter drops a send that comes within 5s of the last one
    (plugins/platforms/photon/adapter.py:81 `_TYPING_COOLDOWN_SECONDS`). here the channel's watch
    loop ticks every ~2s and `every` is the shortest gap between two sends: imessage and telegram
    4s (the bubble lasts 5s; a 5s gap on a 2s tick would really be 6s). discord has its own
    refresh in services/jarvis_discord.py (8s).

    `send(space, on)` is the channel's own coroutine. a failed send is dropped: presence is
    polish and must never break the run watcher.
    """

    def __init__(self, send, every: float, clock=time.monotonic):
        self._send = send
        self.every = every
        self._clock = clock
        self.last: dict[str, float] = {}

    async def __call__(self, space: str, on: bool) -> None:
        if on:
            self.last[space] = self._clock()
        else:
            self.last.pop(space, None)
        with contextlib.suppress(Exception):
            await self._send(space, on)

    async def tick(self, runs: dict) -> None:
        """send "typing" again for every chat with a run that is working (not waiting on the owner)."""
        now = self._clock()
        for space in {i["space"] for i in runs.values() if not i.get("paused")}:
            if now - self.last.get(space, float("-inf")) >= self.every:
                await self(space, True)


def start_work(kind: str, space: str, message_id: str, text: str) -> str:
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
            origin={"kind": kind, "channel_id": space, "message_id": message_id},
        )
        db.commit()
        return run.id
    finally:
        db.close()


async def maybe_answer(runs: dict, space: str, text: str, reply) -> bool:
    """a reply to the question Aide just asked here answers it."""
    from core.database import JarvisRunPrompt, SessionLocal
    from services import jarvis_handoff
    from services.jarvis_store import answer_choice, json_value

    ours = [run_id for run_id, info in runs.items() if info["space"] == space]
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


async def watch_once(runs: dict, reply, typing, log: logging.Logger) -> None:
    """send each run's answer when it ends, and its questions while it waits."""
    from core.database import DelegatedAction, JarvisRun, JarvisRunPrompt, SessionLocal
    from services.jarvis_store import json_value

    db = SessionLocal()
    try:
        for run_id, info in list(runs.items()):
            run = db.get(JarvisRun, run_id)
            if run is None:
                await typing(info["space"], False)
                runs.pop(run_id, None)
                continue
            waiting = db.query(JarvisRunPrompt).filter_by(run_id=run_id, state="pending").all()
            for prompt in waiting:
                if prompt.id in info["told"]:
                    continue
                info["told"].add(prompt.id)
                await typing(info["space"], False)
                if prompt.kind == "choice":
                    options = [str(o) for o in json_value(prompt.options, list)]
                    listed = "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1))
                    await reply(
                        info["space"],
                        f"{prompt.question}\n{listed}\nreply with a number or the option.",
                    )
                else:
                    await reply(
                        info["space"],
                        f"this needs your ok in Aide: {prompt.action or prompt.question}. "
                        "approvals only happen inside alles, not over text.",
                    )
            # tool approvals (shell, file writes...) wait on the conversation, not as a run
            # prompt, so look for them by the run's conversation too
            approvals = (
                db.query(DelegatedAction)
                .filter(
                    DelegatedAction.session_id == run.session_id,
                    DelegatedAction.state == "pending",
                    DelegatedAction.created_at >= run.created_at,
                )
                .all()
            )
            # no typing bubble while the run waits on the owner (hermes `_typing_paused`)
            info["paused"] = bool(waiting or approvals)
            for action in approvals:
                if action.id in info["told"]:
                    continue
                info["told"].add(action.id)
                await typing(info["space"], False)
                await reply(
                    info["space"],
                    f"this needs your ok in Aide: {action.action}. "
                    "approvals only happen inside alles, not over text.",
                )
            if run.state in DONE:
                await typing(info["space"], False)
                text = (run.result_summary or "").strip() if run.state == "succeeded" else ""
                if not text:
                    text = {
                        "failed": f"that didn't work: {run.safe_error or 'Aide could not finish'}",
                        "cancelled": "stopped.",
                    }.get(run.state, "I lost track of that one; check Aide.")
                await reply(info["space"], text[:6000])
                runs.pop(run_id, None)
    except Exception as exc:
        log.warning("%s run watch failed: %s", log.name, type(exc).__name__)
    finally:
        db.close()

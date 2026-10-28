"""what every "text Aide from a chat app" channel shares.

a message becomes background work in Aide's main conversation. a question with choices goes back
as a numbered list and a reply answers it. approvals stay inside alles, because the chat app's
servers relay every message and a relay must not be able to say yes for the owner. the answer is
sent when the run ends.

each channel keeps its own `runs` dict (run id -> {"space", "told"}) and passes its own `reply`
and `typing` coroutines.
"""

from __future__ import annotations

import logging

DONE = {"succeeded", "failed", "cancelled", "interrupted", "uncertain"}


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
                runs.pop(run_id, None)
                continue
            for prompt in db.query(JarvisRunPrompt).filter_by(run_id=run_id, state="pending").all():
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

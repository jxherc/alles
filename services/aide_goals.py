"""standing goals: an aim Aide keeps working on, waking on a rhythm.

a goal is an Aide workflow (marked with GOAL_OWNER) plus one trigger and an AideGoal row.
before each run the agent gets the aim and what it noted last time; each run ends with a small
fenced block that says what to remember, whether to tell the owner, and whether it is done.
the owner hears about a goal only for news, a question or an approval.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from core.database import AideGoal, JarvisRun, JarvisRunPrompt, JarvisTrigger, JarvisWorkflow
from services.jarvis_store import json_value

log = logging.getLogger("alles.goals")

GOAL_OWNER = "aide_goal_v1"
NOTES_LIMIT = 4000
EVERY = {"hour": 3600, "six_hours": 6 * 3600, "day": 86400, "week": 7 * 86400}
MODES = {"ask": "approve", "act": "full_auto"}

_TAIL = re.compile(r"```goal\s*(\{.*?\})\s*```\s*$", re.S)

CLOSING = """

when you are done with this check, end your reply with this block and nothing after it:
```goal
{"notes": "what to remember for next time: facts found, what you checked, what changed", "notify": false, "headline": "one short line for the owner", "done": false}
```
set "notify" to true only when there is news the owner would want or something needs a decision.
set "done" to true only when the goal is fully reached and nothing is left to watch."""


def short_name(aim: str) -> str:
    """'keep an eye on my tasks: tell me if…' reads as 'keep an eye on my tasks'."""
    first = aim.strip().splitlines()[0]
    clause = re.split(r"[:.;!?]\s", first + " ", maxsplit=1)[0].strip()
    name = clause if len(clause) >= 8 else first
    return name if len(name) <= 60 else name[:57].rsplit(" ", 1)[0] + "…"


def is_goal(workflow) -> bool:
    return bool(workflow) and (
        json_value(workflow.delivery_policy, dict).get("aide_schedule_owner") == GOAL_OWNER
    )


def permission(workflow) -> str:
    mode = json_value(workflow.delivery_policy, dict).get("goal_mode", "ask")
    return MODES.get(mode, "approve")


def state_for(db, workflow) -> AideGoal:
    row = db.get(AideGoal, workflow.id)
    if row is None:
        row = AideGoal(workflow_id=workflow.id)
        db.add(row)
        db.flush()
    return row


def request_for(db, workflow, request: str) -> str:
    """the run's prompt: the aim, how far it got, and the closing block it must write."""
    goal = state_for(db, workflow)
    last = goal.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if goal.last_checked_at else "never"
    notes = goal.notes.strip() or "nothing yet; this is the first check."
    return (
        "you are working on a standing goal for the owner.\n"
        f"goal: {request.strip()}\n"
        f"this is check {goal.run_count + 1}. last check: {last}.\n"
        f"what you noted last time:\n{notes}\n\n"
        "do the next useful step toward the goal with your tools. don't redo work your notes "
        "already cover. if you need the owner's decision, ask with ask_user." + CLOSING
    )


def read_tail(text: str) -> tuple[str, dict]:
    """split the reply into what the owner reads and the goal block."""
    found = _TAIL.search(text or "")
    if not found:
        return text or "", {}
    try:
        data = json.loads(found.group(1))
    except ValueError:
        return text, {}
    return text[: found.start()].rstrip(), data if isinstance(data, dict) else {}


def _stop(db, workflow, goal: AideGoal, status: str) -> None:
    goal.status = status
    workflow.enabled = False
    for trigger in db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).all():
        trigger.enabled = False
        trigger.next_run_at = None


def finish(db, run, workflow, state: str, result: str, now: datetime) -> tuple[str, dict | None]:
    """save what the run learned; returns the reply to keep and an alert to send, if any."""
    goal = state_for(db, workflow)
    clean, data = read_tail(result)
    # artifact wrappers mean something in chat, not in a short goal summary
    clean = re.sub(r"</?aide-artifact\b[^>]*>", "", clean).strip()
    goal.last_run_id = run.id
    goal.last_checked_at = now
    if state != "succeeded":
        return clean, None
    goal.run_count = (goal.run_count or 0) + 1
    if isinstance(data.get("notes"), str) and data["notes"].strip():
        goal.notes = data["notes"].strip()[:NOTES_LIMIT]
    headline = str(data.get("headline") or "").strip()[:300]
    if headline:
        goal.last_headline = headline
    done = data.get("done") is True
    if done:
        _stop(db, workflow, goal, "done")
    elif goal.max_runs and goal.run_count >= goal.max_runs:
        _stop(db, workflow, goal, "finished")
    elif goal.until and now >= goal.until:
        _stop(db, workflow, goal, "finished")
    if data.get("notify") is True or done:
        body = headline or (clean.strip().splitlines() or ["the goal has news"])[0][:300]
        title = f"{'done: ' if done else ''}{workflow.name}"
        return clean, {"title": title, "body": body, "goal_id": workflow.id}
    return clean, None


def expired(db, workflow, now: datetime) -> bool:
    """checked before a goal is due; a goal past its end date stops instead of running."""
    goal = db.get(AideGoal, workflow.id)
    if goal is None or not goal.until or now < goal.until:
        return False
    _stop(db, workflow, goal, "finished")
    return True


async def alert(notice: dict) -> None:
    """push to every subscribed browser and send the discord/telegram note, if set up."""
    from services import notify, push_delivery

    url = f"/?view=scheduled&tab=goals&goal={notice['goal_id']}"
    try:
        await push_delivery.broadcast_result(
            {
                "title": notice["title"],
                "body": notice["body"],
                "url": url,
                "tag": f"goal-{notice['goal_id']}",
            }
        )
    except Exception as exc:
        log.warning("goal push failed: %s", type(exc).__name__)
    if notify.configured():
        await notify.send(f"{notice['title']}: {notice['body']}")


async def alert_waiting() -> int:
    """tell the owner once when a goal run stops to ask a question or wait for approval."""
    from core.database import SessionLocal

    db = SessionLocal()
    notices = []
    try:
        rows = (
            db.query(JarvisRunPrompt, JarvisRun, JarvisWorkflow)
            .join(JarvisRun, JarvisRun.id == JarvisRunPrompt.run_id)
            .join(JarvisWorkflow, JarvisWorkflow.id == JarvisRun.workflow_id)
            .filter(JarvisRunPrompt.state == "pending")
            .all()
        )
        for prompt, run, workflow in rows:
            if not is_goal(workflow):
                continue
            goal = state_for(db, workflow)
            seen = json_value(goal.alerted_json, list)
            if prompt.id in seen:
                continue
            goal.alerted_json = json.dumps((seen + [prompt.id])[-50:])
            kind = "approve this" if prompt.kind == "approval" else "a question"
            notices.append(
                {
                    "title": f"{workflow.name} needs you",
                    "body": f"{kind}: {prompt.question[:240]}",
                    "goal_id": workflow.id,
                }
            )
        db.commit()
    finally:
        db.close()
    for notice in notices:
        await alert(notice)
    return len(notices)


def running_run(db, workflow):
    return (
        db.query(JarvisRun)
        .filter(JarvisRun.workflow_id == workflow.id, JarvisRun.state.in_(("queued", "running")))
        .first()
    )


def public(db, workflow, trigger) -> dict:
    goal = db.get(AideGoal, workflow.id)
    policy = json_value(workflow.delivery_policy, dict)
    waiting = 0
    if goal and goal.last_run_id:
        waiting = (
            db.query(JarvisRunPrompt)
            .join(JarvisRun, JarvisRun.id == JarvisRunPrompt.run_id)
            .filter(JarvisRun.workflow_id == workflow.id, JarvisRunPrompt.state == "pending")
            .count()
        )
    last = db.get(JarvisRun, goal.last_run_id) if goal and goal.last_run_id else None
    active = running_run(db, workflow)
    return {
        "id": workflow.id,
        "aim": workflow.prompt or "",
        "name": workflow.name,
        "every": policy.get("goal_every", "day"),
        "mode": policy.get("goal_mode", "ask"),
        "enabled": bool(workflow.enabled),
        "status": goal.status if goal else "active",
        "notes": goal.notes if goal else "",
        "headline": goal.last_headline if goal else "",
        "checks": goal.run_count if goal else 0,
        "max_runs": goal.max_runs if goal else None,
        "until": goal.until.isoformat() if goal and goal.until else None,
        "last_checked_at": goal.last_checked_at.isoformat()
        if goal and goal.last_checked_at
        else None,
        "next_check_at": trigger.next_run_at.isoformat()
        if trigger and trigger.next_run_at
        else None,
        "running": active is not None,
        "waiting": waiting,
        "last_run": {
            "id": last.id,
            "state": last.state,
            "summary": last.result_summary or "",
            "error": last.safe_error or "",
        }
        if last
        else None,
    }

"""automation rules CRUD — the engine lives in services/automations.py"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import AutomationAttempt, AutomationRule, JarvisWorkflow, get_db
from services.automations import ACTIONS, TRIGGERS

router = APIRouter(prefix="/api")

_TRIGGER_META = [
    {
        "value": "mail_from",
        "label": "mail arrives from…",
        "arg": "sender contains (e.g. landlord@)",
    },
    {"value": "sub_renewing", "label": "subscription renews within…", "arg": "days (e.g. 3)"},
    {"value": "day_event_near", "label": "days-event is within…", "arg": "days (e.g. 7)"},
    {"value": "daily_at", "label": "every day at…", "arg": "HH:MM (server time)"},
    {"value": "doc_tag", "label": "doc saved with #tag…", "arg": "tag (e.g. invoice)"},
    {
        "value": "agent_tool",
        "label": "agent uses a tool…",
        "arg": "tool name or glob (e.g. write_* or *)",
    },
]
_ACTION_META = [
    {
        "value": "create_task",
        "label": "create a task",
        "arg": "task title — {from} {subject} {name} {date}",
    },
    {
        "value": "push",
        "label": "push a notification",
        "arg": "notification text — {from} {subject} {name} {date}",
    },
    {
        "value": "create_note",
        "label": "create a note",
        "arg": "note content — {from} {subject} {name} {date} {path}",
    },
    {"value": "push_digest", "label": "push my day digest", "arg": "(no template needed)"},
    {
        "value": "notify",
        "label": "send to discord / telegram",
        "arg": "message text — {from} {subject} {name} {date}",
    },
    {
        "value": "notify_digest",
        "label": "send my day digest to discord / telegram",
        "arg": "(no template needed)",
    },
]


def _fmt(r: AutomationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "trigger": r.trigger,
        "trigger_arg": r.trigger_arg,
        "action": r.action,
        "action_arg": r.action_arg,
        "enabled": r.enabled,
        "enabled_intent": bool(r.enabled_intent),
        "migrated_workflow_id": r.migrated_workflow_id,
        "migration_state": "needs_review" if r.migrated_workflow_id else "legacy",
        "created_at": r.created_at.isoformat(),
    }


def _fmt_attempt(attempt: AutomationAttempt) -> dict:
    return {
        "id": attempt.id,
        "status": attempt.status,
        "action": attempt.action,
        "error": attempt.error or "",
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
    }


@router.get("/automations/options")
def options():
    return {"triggers": _TRIGGER_META, "actions": _ACTION_META}


@router.get("/automations")
def list_rules(db: DbSession = Depends(get_db)):
    output = []
    for rule in db.query(AutomationRule).order_by(AutomationRule.created_at).all():
        item = _fmt(rule)
        latest = (
            db.query(AutomationAttempt)
            .filter_by(rule_id=rule.id)
            .order_by(AutomationAttempt.started_at.desc())
            .first()
        )
        item["last_attempt"] = _fmt_attempt(latest) if latest else None
        output.append(item)
    return output


@router.get("/automations/{rid}/attempts")
def list_attempts(rid: str, limit: int = 20, db: DbSession = Depends(get_db)):
    if not db.get(AutomationRule, rid):
        raise HTTPException(404)
    safe_limit = max(1, min(limit, 100))
    rows = (
        db.query(AutomationAttempt)
        .filter_by(rule_id=rid)
        .order_by(AutomationAttempt.started_at.desc())
        .limit(safe_limit)
        .all()
    )
    return [_fmt_attempt(row) for row in rows]


class RuleBody(BaseModel):
    name: str = ""
    trigger: str
    trigger_arg: str = ""
    action: str
    action_arg: str = ""


def _validate_trigger_arg(trigger: str, trigger_arg: str):
    arg = (trigger_arg or "").strip()
    if trigger == "daily_at":
        import re

        m = re.fullmatch(r"(\d{2}):(\d{2})", arg)
        # 2-digit each is required so the scheduler's HH:MM string-compare works; also reject
        # times that fit the shape but no clock ever reaches ("25:99" → rule silently never fires)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise HTTPException(400, "daily_at needs a valid HH:MM time (00:00–23:59)")
    if trigger in ("sub_renewing", "day_event_near"):
        try:
            int(arg or "3")
        except ValueError:
            raise HTTPException(400, "this trigger needs a number of days")


@router.post("/automations")
def create_rule(body: RuleBody, db: DbSession = Depends(get_db)):
    if body.trigger not in TRIGGERS:
        raise HTTPException(400, f"trigger must be one of {', '.join(TRIGGERS)}")
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(ACTIONS)}")
    _validate_trigger_arg(body.trigger, body.trigger_arg)
    name = body.name.strip() or f"{body.trigger} → {body.action}"
    r = AutomationRule(
        name=name,
        trigger=body.trigger,
        trigger_arg=body.trigger_arg.strip(),
        action=body.action,
        action_arg=body.action_arg,
    )
    db.add(r)
    db.flush()
    from services.automation_migration import sync_migrated_rule

    sync_migrated_rule(db, r)
    db.commit()
    db.refresh(r)
    return _fmt(r)


class RulePatch(BaseModel):
    name: str | None = None
    trigger: str | None = None
    trigger_arg: str | None = None
    action: str | None = None
    action_arg: str | None = None
    enabled: bool | None = None


@router.patch("/automations/{rid}")
def patch_rule(rid: str, body: RulePatch, db: DbSession = Depends(get_db)):
    r = db.get(AutomationRule, rid)
    if not r:
        raise HTTPException(404)
    if body.trigger is not None and body.trigger not in TRIGGERS:
        raise HTTPException(400, "unknown trigger")
    if body.action is not None and body.action not in ACTIONS:
        raise HTTPException(400, "unknown action")
    # validate the arg against the trigger it'll actually run under (new one if changing, else current)
    if body.trigger is not None or body.trigger_arg is not None:
        eff_trigger = body.trigger if body.trigger is not None else r.trigger
        eff_arg = body.trigger_arg if body.trigger_arg is not None else r.trigger_arg
        _validate_trigger_arg(eff_trigger, eff_arg)
    for f in ("name", "trigger", "trigger_arg", "action", "action_arg", "enabled"):
        v = getattr(body, f)
        if v is not None:
            setattr(r, f, v)
    if body.enabled is not None:
        r.enabled_intent = body.enabled
    if r.migrated_workflow_id:
        from services.automation_migration import sync_migrated_rule

        sync_migrated_rule(db, r)
    db.commit()
    return _fmt(r)


@router.delete("/automations/{rid}")
def delete_rule(rid: str, db: DbSession = Depends(get_db)):
    r = db.get(AutomationRule, rid)
    if not r:
        raise HTTPException(404)
    migrated_workflow = (
        db.get(JarvisWorkflow, r.migrated_workflow_id)
        if r.migrated_workflow_id
        else None
    )
    # Production SQLite cascades this foreign key. Delete explicitly too so
    # alternate/test engines cannot leave orphaned attempt history.
    db.query(AutomationAttempt).filter_by(rule_id=rid).delete()
    if migrated_workflow:
        db.delete(migrated_workflow)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/automations/{rid}/test")
async def test_rule(rid: str, db: DbSession = Depends(get_db)):
    """fire the rule's action once with sample data so you can see the result"""
    r = db.get(AutomationRule, rid)
    if not r:
        raise HTTPException(404)
    if r.migrated_workflow_id:
        raise HTTPException(409, "migrated automation must be reviewed in Jarvis")
    from services.automations import _fire

    sample = {
        "from": "sample@example.com",
        "subject": "sample subject",
        "name": "sample",
        "date": "2026-01-01",
        "path": "sample.md",
        "tag": r.trigger_arg or "tag",
        "price": "9.99",
        "dedupe": f"manual-test:{uuid.uuid4()}",
    }
    result = await _fire(db, r, sample)
    if result.get("status") == "succeeded":
        return {"ok": True, "note": "action executed with sample data", "attempt": result}
    status_code = 409 if result.get("status") in ("running", "uncertain") else 502
    raise HTTPException(
        status_code,
        detail={
            "message": "the action was not confirmed; check its attempt history",
            "attempt": result,
        },
    )

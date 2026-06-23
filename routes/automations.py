"""automation rules CRUD — the engine lives in services/automations.py"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, AutomationRule
from services.automations import TRIGGERS, ACTIONS

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
    {"value": "agent_tool", "label": "agent uses a tool…", "arg": "tool name or glob (e.g. write_* or *)"},
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
        "created_at": r.created_at.isoformat(),
    }


@router.get("/automations/options")
def options():
    return {"triggers": _TRIGGER_META, "actions": _ACTION_META}


@router.get("/automations")
def list_rules(db: DbSession = Depends(get_db)):
    return [_fmt(r) for r in db.query(AutomationRule).order_by(AutomationRule.created_at).all()]


class RuleBody(BaseModel):
    name: str = ""
    trigger: str
    trigger_arg: str = ""
    action: str
    action_arg: str = ""


@router.post("/automations")
def create_rule(body: RuleBody, db: DbSession = Depends(get_db)):
    if body.trigger not in TRIGGERS:
        raise HTTPException(400, f"trigger must be one of {', '.join(TRIGGERS)}")
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(ACTIONS)}")
    if body.trigger == "daily_at":
        import re

        if not re.fullmatch(r"\d{2}:\d{2}", body.trigger_arg.strip()):
            raise HTTPException(400, "daily_at needs a HH:MM time")
    if body.trigger in ("sub_renewing", "day_event_near"):
        try:
            int(body.trigger_arg or "3")
        except ValueError:
            raise HTTPException(400, "this trigger needs a number of days")
    name = body.name.strip() or f"{body.trigger} → {body.action}"
    r = AutomationRule(
        name=name,
        trigger=body.trigger,
        trigger_arg=body.trigger_arg.strip(),
        action=body.action,
        action_arg=body.action_arg,
    )
    db.add(r)
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
    for f in ("name", "trigger", "trigger_arg", "action", "action_arg", "enabled"):
        v = getattr(body, f)
        if v is not None:
            setattr(r, f, v)
    db.commit()
    return _fmt(r)


@router.delete("/automations/{rid}")
def delete_rule(rid: str, db: DbSession = Depends(get_db)):
    r = db.get(AutomationRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/automations/{rid}/test")
async def test_rule(rid: str, db: DbSession = Depends(get_db)):
    """fire the rule's action once with sample data so you can see the result"""
    r = db.get(AutomationRule, rid)
    if not r:
        raise HTTPException(404)
    from services.automations import _fire

    sample = {
        "from": "sample@example.com",
        "subject": "sample subject",
        "name": "sample",
        "date": "2026-01-01",
        "path": "sample.md",
        "tag": r.trigger_arg or "tag",
        "price": "9.99",
        "dedupe": "test",
    }
    await _fire(db, r, sample)
    return {"ok": True, "note": "action executed with sample data"}

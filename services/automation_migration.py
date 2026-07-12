"""Convert legacy automation rules into paused, reviewable Jarvis records."""

from sqlalchemy.orm import Session as DbSession

from core.database import AutomationRule, JarvisTrigger, JarvisWorkflow, SessionLocal
from core.settings import load_settings
from services.jarvis_store import json_text

_ACTION_CAPABILITIES = {
    "create_task": ["state"],
    "create_note": ["write"],
    "push": ["delivery"],
    "push_digest": ["delivery"],
    "notify": ["delivery"],
    "notify_digest": ["delivery"],
}


def _trigger_values(rule: AutomationRule, timezone_name: str) -> tuple[str, dict, str]:
    if rule.trigger == "daily_at":
        return "schedule", {"time": rule.trigger_arg or "08:00"}, timezone_name
    return (
        "event",
        {
            "event_type": f"legacy.{rule.trigger}",
            "legacy_trigger": rule.trigger,
            "legacy_argument": rule.trigger_arg or "",
        },
        timezone_name,
    )


def sync_migrated_rule(
    db: DbSession,
    rule: AutomationRule,
    *,
    timezone_name: str | None = None,
) -> JarvisWorkflow:
    timezone_name = timezone_name or str(load_settings().get("timezone") or "UTC")
    intent = bool(rule.enabled) if rule.enabled_intent is None else bool(rule.enabled_intent)
    workflow = None
    if rule.migrated_workflow_id:
        workflow = db.get(JarvisWorkflow, rule.migrated_workflow_id)
    if not workflow:
        workflow = (
            db.query(JarvisWorkflow).filter_by(legacy_automation_id=rule.id).first()
        )
    if not workflow:
        workflow = JarvisWorkflow(
            name=rule.name or f"{rule.trigger} → {rule.action}",
            legacy_automation_id=rule.id,
        )
        db.add(workflow)
        db.flush()
    workflow.name = rule.name or f"{rule.trigger} → {rule.action}"
    workflow.purpose = "migrated legacy automation; review before enabling"
    workflow.prompt = rule.action_arg or ""
    workflow.deterministic_action = rule.action
    workflow.capability_ceiling = json_text(
        _ACTION_CAPABILITIES.get(rule.action, []), expected=list
    )
    workflow.delivery_policy = json_text(
        {"legacy_action": rule.action} if rule.action.startswith(("push", "notify")) else {},
        expected=dict,
    )
    workflow.enabled = False
    workflow.review_state = "needs_review"
    workflow.legacy_enabled_intent = intent
    trigger = db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).first()
    if not trigger:
        trigger = JarvisTrigger(workflow_id=workflow.id)
        db.add(trigger)
    kind, config, timezone_value = _trigger_values(rule, timezone_name)
    trigger.kind = kind
    trigger.config = json_text(config, expected=dict)
    trigger.timezone = timezone_value
    trigger.enabled = False
    trigger.next_run_at = None
    rule.migrated_workflow_id = workflow.id
    rule.enabled_intent = intent
    rule.enabled = False
    db.flush()
    return workflow


def migrate_legacy_automations() -> int:
    timezone_name = str(load_settings().get("timezone") or "UTC")
    db = SessionLocal()
    created = 0
    try:
        rules = db.query(AutomationRule).all()
        for rule in rules:
            if rule.migrated_workflow_id and db.get(JarvisWorkflow, rule.migrated_workflow_id):
                if rule.enabled:
                    rule.enabled_intent = True
                    rule.enabled = False
                continue
            sync_migrated_rule(db, rule, timezone_name=timezone_name)
            created += 1
        db.commit()
        return created
    finally:
        db.close()

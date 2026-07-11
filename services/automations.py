"""
personal automation rules — "when this happens, do that".

triggers
  mail_from <substr>      a new mail arrives whose sender matches (IMAP polled ~30s)
  sub_renewing <days>     a subscription renews within N days
  day_event_near <days>   a days-event is within N days
  daily_at <HH:MM>        every day at that time (server clock)
  doc_tag <tag>           a doc is saved containing #tag (fires from the save route)

actions
  create_task    action_arg = task title template
  push           action_arg = notification body template
  create_note    action_arg = note content template
  push_digest    push a summary of today (events/tasks/renewals) — for daily_at
  notify         send action_arg text to discord / telegram
  notify_digest  send today's briefing to discord / telegram — for daily_at

templates may use {from} {subject} {name} {date} {path} {tag} {price} — unknown
placeholders are left as-is rather than crashing the rule.
"""

import asyncio
import fnmatch
import hashlib
import json
import logging
import uuid
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from core.database import AutomationAttempt, AutomationRule, SessionLocal, Task

log = logging.getLogger("aide.automations")

TRIGGERS = ("mail_from", "sub_renewing", "day_event_near", "daily_at", "doc_tag", "agent_tool")
ACTIONS = ("create_task", "push", "create_note", "push_digest", "notify", "notify_digest")

_MAIL_POLL_EVERY = 30  # seconds between IMAP polls for mail_from rules (pooled connections + 10s list cache keep this cheap)

ATTEMPT_RUNNING = "running"
ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED = "failed"
ATTEMPT_UNCERTAIN = "uncertain"


class _DefiniteActionFailure(RuntimeError):
    """The action did not happen, so its outcome is known."""


class _UncertainActionFailure(RuntimeError):
    """The action may have happened and must not be retried automatically."""


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def _render(tpl: str, ctx: dict) -> str:
    return (tpl or "").format_map(_Safe(**{k: str(v) for k, v in ctx.items()}))


def _state(rule) -> dict:
    try:
        return json.loads(rule.state or "{}")
    except Exception:
        return {}


def _hashed_occurrence(ctx: dict) -> str:
    """Return a stable, content-free identity for this trigger occurrence."""
    raw = str(ctx.get("dedupe") or f"event:{uuid.uuid4()}")
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()


def _attempt_result(attempt, *, executed: bool) -> dict:
    return {
        "id": attempt.id,
        "status": attempt.status,
        "action": attempt.action,
        "executed": executed,
        "error": attempt.error or "",
    }


def _was_successful(result) -> bool:
    return isinstance(result, dict) and result.get("status") == ATTEMPT_SUCCEEDED


def _claim_attempt(db, rule, ctx: dict) -> tuple[AutomationAttempt, bool]:
    occurrence_key = _hashed_occurrence(ctx)
    existing = (
        db.query(AutomationAttempt)
        .filter_by(rule_id=rule.id, occurrence_key=occurrence_key)
        .first()
    )
    if existing:
        return existing, False

    attempt = AutomationAttempt(
        rule_id=rule.id,
        occurrence_key=occurrence_key,
        status=ATTEMPT_RUNNING,
        action=rule.action,
    )
    db.add(attempt)
    try:
        # The claim is durable before any file, push, webhook, or provider side effect.
        db.commit()
        db.refresh(attempt)
        return attempt, True
    except IntegrityError:
        # A concurrent worker won the unique occurrence claim.
        db.rollback()
        existing = (
            db.query(AutomationAttempt)
            .filter_by(rule_id=rule.id, occurrence_key=occurrence_key)
            .one()
        )
        return existing, False


def _finish_attempt(db, attempt, status: str, error: str = "") -> str:
    attempt.status = status
    attempt.error = error[:300]
    attempt.finished_at = datetime.utcnow()
    try:
        db.commit()
        return status
    except Exception:
        # If the action ran but its result could not be saved, leave the durable
        # claim as running. This process will not retry it, and startup changes it
        # to uncertain before any jobs start.
        db.rollback()
        log.warning("automation outcome could not be saved; leaving its claim unresolved")
        return ATTEMPT_UNCERTAIN


def _controlled_error(exc: Exception, fallback: str) -> str:
    if isinstance(exc, (_DefiniteActionFailure, _UncertainActionFailure)):
        return str(exc)[:300]
    return f"{fallback} ({type(exc).__name__})"


def _push_result_status(result: dict) -> None:
    if int(result.get("sent", 0)) > 0:
        return
    if int(result.get("uncertain", 0)) > 0:
        raise _UncertainActionFailure("push delivery outcome could not be confirmed")
    raise _DefiniteActionFailure("no live push subscription received the action")


def _notify_result_status(result: dict) -> None:
    values = tuple(result.values())
    if any(value is True for value in values):
        return
    if any(value is False for value in values):
        raise _UncertainActionFailure("notification delivery outcome could not be confirmed")
    raise _DefiniteActionFailure("no notification channel is configured")


async def _perform_action(db, rule, ctx: dict, text: str) -> None:
    if rule.action == "create_task":
        try:
            db.add(Task(title=text[:300]))
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _DefiniteActionFailure("task creation failed before it was saved") from exc
        return

    if rule.action == "create_note":
        from services import notes_vault

        try:
            notes_vault.create(title=(rule.name or "automation")[:120], content=text)
        except Exception as exc:
            # A filesystem error can happen after the rename reached disk.
            raise _UncertainActionFailure("note creation outcome could not be confirmed") from exc
        return

    if rule.action in ("push", "push_digest"):
        from routes.push import broadcast_result

        if rule.action == "push_digest":
            try:
                body = _digest(db)
            except Exception as exc:
                raise _DefiniteActionFailure("digest creation failed before delivery") from exc
            payload = {
                "title": "your day",
                "body": body,
                "url": "/",
                "tag": f"digest-{rule.id}",
            }
        else:
            payload = {
                "title": rule.name or "alles",
                "body": text[:300],
                "url": "/",
                "tag": f"auto-{rule.id}-{ctx.get('dedupe', '')}",
            }
        try:
            result = await broadcast_result(payload)
        except Exception as exc:
            raise _UncertainActionFailure("push delivery outcome could not be confirmed") from exc
        _push_result_status(result)
        return

    if rule.action in ("notify", "notify_digest"):
        from services import notify

        if rule.action == "notify_digest":
            try:
                body = _digest(db)
            except Exception as exc:
                raise _DefiniteActionFailure("digest creation failed before delivery") from exc
        else:
            body = text[:1500]
        try:
            result = await notify.send(body)
        except Exception as exc:
            raise _UncertainActionFailure("notification outcome could not be confirmed") from exc
        _notify_result_status(result)
        return

    raise _DefiniteActionFailure("automation action is no longer supported")


async def _fire(db, rule, ctx: dict):
    """Claim and run one rule occurrence, returning its durable outcome."""
    text = (
        _render(rule.action_arg, ctx)
        or ctx.get("subject")
        or ctx.get("name")
        or rule.name
        or "automation"
    )
    try:
        attempt, claimed = _claim_attempt(db, rule, ctx)
    except Exception as exc:
        db.rollback()
        log.warning("automation action was not run because its durable claim failed")
        return {
            "id": "",
            "status": ATTEMPT_FAILED,
            "action": rule.action,
            "executed": False,
            "error": f"claim failed ({type(exc).__name__})",
        }
    if not claimed:
        return _attempt_result(attempt, executed=False)

    try:
        await _perform_action(db, rule, ctx, text)
    except asyncio.CancelledError:
        _finish_attempt(
            db,
            attempt,
            ATTEMPT_UNCERTAIN,
            "server stopped before the action outcome was confirmed",
        )
        raise
    except _DefiniteActionFailure as exc:
        status = _finish_attempt(db, attempt, ATTEMPT_FAILED, _controlled_error(exc, "failed"))
    except Exception as exc:
        status = _finish_attempt(
            db,
            attempt,
            ATTEMPT_UNCERTAIN,
            _controlled_error(exc, "action outcome could not be confirmed"),
        )
    else:
        status = _finish_attempt(db, attempt, ATTEMPT_SUCCEEDED)
        if status == ATTEMPT_SUCCEEDED:
            log.info(f"automation fired: {rule.name or rule.id} -> {rule.action}")

    db.refresh(attempt)
    result = _attempt_result(attempt, executed=True)
    # A failed outcome save is reported as uncertain even if the still-running
    # row could not be updated. Startup will reconcile that row before jobs run.
    result["status"] = status
    return result


def reconcile_interrupted_attempts() -> int:
    """Turn claims left running by an earlier process into terminal uncertainty."""
    db = SessionLocal()
    try:
        rows = db.query(AutomationAttempt).filter_by(status=ATTEMPT_RUNNING).all()
        if not rows:
            return 0
        now = datetime.utcnow()
        for attempt in rows:
            attempt.status = ATTEMPT_UNCERTAIN
            attempt.error = "server stopped before the action outcome was confirmed"
            attempt.finished_at = now
        db.commit()
        return len(rows)
    finally:
        db.close()


def _digest(db) -> str:
    """day summary for push — the full briefing (events, tasks, habits, reading, health)"""
    from services.briefing import compose_briefing

    return compose_briefing(db)["body"]


async def run_automations():
    """called from the background loop every tick (~30s)."""
    db = SessionLocal()
    try:
        rules = db.query(AutomationRule).filter(AutomationRule.enabled == True).all()
        if not rules:
            return
        now = datetime.now()
        today = date.today()
        for rule in rules:
            try:
                st = _state(rule)
                if rule.trigger == "daily_at":
                    hhmm = (rule.trigger_arg or "08:00").strip()
                    if now.strftime("%H:%M") >= hhmm and st.get("last_daily") != today.isoformat():
                        result = await _fire(
                            db, rule, {"date": today.isoformat(), "dedupe": today.isoformat()}
                        )
                        if _was_successful(result):
                            st["last_daily"] = today.isoformat()
                            rule.state = json.dumps(st)
                            db.commit()

                elif rule.trigger == "sub_renewing":
                    from core.database import Subscription
                    from routes.subscriptions import _parse as sub_parse

                    days = int(rule.trigger_arg or 3)
                    done = st.get("done", {})
                    for s in db.query(Subscription).filter(Subscription.active == True).all():
                        key = f"{s.id}:{s.next_due}"
                        if key in done:
                            continue
                        if 0 <= (sub_parse(s.next_due) - today).days <= days:
                            result = await _fire(
                                db,
                                rule,
                                {
                                    "name": s.name,
                                    "date": s.next_due,
                                    "price": s.price,
                                    "dedupe": key,
                                },
                            )
                            if _was_successful(result):
                                done[key] = 1
                                st["done"] = _trim(done)
                                rule.state = json.dumps(st)
                                db.commit()

                elif rule.trigger == "day_event_near":
                    from core.database import DayEvent
                    from routes.days import _occurrence
                    from routes.days import _parse as day_parse

                    days = int(rule.trigger_arg or 3)
                    done = st.get("done", {})
                    for ev in db.query(DayEvent).all():
                        orig = day_parse(ev.date)
                        if ev.repeat in ("yearly", "monthly"):
                            target, _ = _occurrence(orig, today, ev.repeat)
                        else:
                            target = orig
                            if target < today:
                                continue
                        key = f"{ev.id}:{target.isoformat()}"
                        if key in done:
                            continue
                        if 0 <= (target - today).days <= days:
                            result = await _fire(
                                db,
                                rule,
                                {"name": ev.name, "date": target.isoformat(), "dedupe": key},
                            )
                            if _was_successful(result):
                                done[key] = 1
                                st["done"] = _trim(done)
                                rule.state = json.dumps(st)
                                db.commit()

                elif rule.trigger == "mail_from":
                    if (now.timestamp() - st.get("last_poll", 0)) < _MAIL_POLL_EVERY:
                        continue
                    st["last_poll"] = now.timestamp()
                    rule.state = json.dumps(st)
                    db.commit()
                    await _check_mail_rule(db, rule, st)
            except Exception as e:
                log.warning("automation rule failed: %s", type(e).__name__)
    finally:
        db.close()


def _trim(done: dict, keep: int = 200) -> dict:
    if len(done) <= keep:
        return done
    return dict(list(done.items())[-keep:])


async def _check_mail_rule(db, rule, st):
    from core.database import MailAccount
    from services import mail as mailsvc

    needle = (rule.trigger_arg or "").lower().strip()
    if not needle:
        return
    seen_uids = st.get("uids", {})
    for a in db.query(MailAccount).all():
        acct = {
            "imap_host": a.imap_host,
            "imap_port": a.imap_port,
            "smtp_host": a.smtp_host,
            "smtp_port": a.smtp_port,
            "username": a.username,
            "password": a.password,
            "email": a.email,
            "use_ssl": a.use_ssl,
        }
        try:
            msgs = await asyncio.to_thread(mailsvc.fetch_inbox, acct, "INBOX", 10)
        except Exception as e:
            log.warning("automation mail poll failed: %s", type(e).__name__)
            continue
        top = max((int(m.get("uid", 0)) for m in msgs), default=0)
        first_run = a.id not in seen_uids
        last = int(seen_uids.get(a.id, 0))
        seen_uids[a.id] = max(top, last)
        if first_run:  # don't storm actions for historical mail on this account
            continue
        for m in msgs:
            if int(m.get("uid", 0)) <= last:
                continue
            if needle not in (m.get("from", "") or "").lower():
                continue
            await _fire(
                db,
                rule,
                {
                    "from": m.get("from", ""),
                    "subject": m.get("subject", ""),
                    "date": m.get("date", ""),
                    "dedupe": f"{a.id}:{m.get('uid')}",
                },
            )
    st["uids"] = seen_uids
    rule.state = json.dumps(st)
    db.commit()


async def on_agent_tool(tool: str, args: dict, result, run_id: str = ""):
    """called from the agent run loop after every tool — fires agent_tool rules (10a).

    trigger_arg is an fnmatch glob over the tool name (e.g. write_* or *). No once-per
    dedupe: a hook is meant to fire each time its tool runs.
    """
    db = SessionLocal()
    try:
        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.enabled == True, AutomationRule.trigger == "agent_tool")
            .all()
        )
        for rule in rules:
            glob = (rule.trigger_arg or "*").strip() or "*"
            if not fnmatch.fnmatch(tool, glob):
                continue
            call_id = result.get("call_id", "") if isinstance(result, dict) else ""
            event_key = f"{run_id}:{call_id}" if run_id and call_id else f"event:{uuid.uuid4()}"
            await _fire(
                db,
                rule,
                {"tool": tool, "name": tool, "run_id": run_id or "", "dedupe": event_key},
            )
    except Exception as e:
        log.warning("agent-tool automation failed: %s", type(e).__name__)
    finally:
        db.close()


async def on_doc_saved(path: str, content: str):
    """called by the docs save route — fires doc_tag rules."""
    db = SessionLocal()
    try:
        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.enabled == True, AutomationRule.trigger == "doc_tag")
            .all()
        )
        for rule in rules:
            tag = (rule.trigger_arg or "").lstrip("#").strip().lower()
            if not tag or f"#{tag}" not in content.lower():
                continue
            st = _state(rule)
            done = st.get("done", {})
            if done.get(path):  # once per doc per rule
                continue
            result = await _fire(
                db,
                rule,
                {"path": path, "tag": tag, "name": path.rsplit("/", 1)[-1], "dedupe": path},
            )
            if _was_successful(result):
                done[path] = 1
                st["done"] = _trim(done)
                rule.state = json.dumps(st)
                db.commit()
    except Exception as e:
        log.warning("document automation failed: %s", type(e).__name__)
    finally:
        db.close()

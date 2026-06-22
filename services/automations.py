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

import json, asyncio, logging, fnmatch
from datetime import datetime, date
from core.database import SessionLocal, AutomationRule, Task, Note

log = logging.getLogger("aide.automations")

TRIGGERS = ("mail_from", "sub_renewing", "day_event_near", "daily_at", "doc_tag", "agent_tool")
ACTIONS = ("create_task", "push", "create_note", "push_digest", "notify", "notify_digest")

_MAIL_POLL_EVERY = 30  # seconds between IMAP polls for mail_from rules (pooled connections + 10s list cache keep this cheap)


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


async def _fire(db, rule, ctx: dict):
    """run one rule's action. context keys depend on the trigger."""
    text = (
        _render(rule.action_arg, ctx)
        or ctx.get("subject")
        or ctx.get("name")
        or rule.name
        or "automation"
    )
    try:
        if rule.action == "create_task":
            db.add(Task(title=text[:300]))
            db.commit()
        elif rule.action == "create_note":
            db.add(Note(title=(rule.name or "automation")[:120], content=text))
            db.commit()
        elif rule.action == "push":
            from routes.push import broadcast

            await broadcast(
                {
                    "title": rule.name or "alles",
                    "body": text[:300],
                    "url": "/",
                    "tag": f"auto-{rule.id}-{ctx.get('dedupe', '')}",
                }
            )
        elif rule.action == "push_digest":
            from routes.push import broadcast

            body = _digest(db)
            await broadcast(
                {"title": "your day", "body": body, "url": "/", "tag": f"digest-{rule.id}"}
            )
        elif rule.action == "notify":
            from services import notify

            await notify.send(text[:1500])
        elif rule.action == "notify_digest":
            from services import notify

            await notify.send(_digest(db))
        log.info(f"automation fired: {rule.name or rule.id} -> {rule.action}")
    except Exception as e:
        log.warning(f"automation action failed ({rule.name or rule.id}): {e}")


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
                        st["last_daily"] = today.isoformat()
                        rule.state = json.dumps(st)
                        db.commit()
                        await _fire(
                            db, rule, {"date": today.isoformat(), "dedupe": today.isoformat()}
                        )

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
                            done[key] = 1
                            st["done"] = _trim(done)
                            rule.state = json.dumps(st)
                            db.commit()
                            await _fire(
                                db,
                                rule,
                                {
                                    "name": s.name,
                                    "date": s.next_due,
                                    "price": s.price,
                                    "dedupe": key,
                                },
                            )

                elif rule.trigger == "day_event_near":
                    from core.database import DayEvent
                    from routes.days import _occurrence, _parse as day_parse

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
                            done[key] = 1
                            st["done"] = _trim(done)
                            rule.state = json.dumps(st)
                            db.commit()
                            await _fire(
                                db,
                                rule,
                                {"name": ev.name, "date": target.isoformat(), "dedupe": key},
                            )

                elif rule.trigger == "mail_from":
                    if (now.timestamp() - st.get("last_poll", 0)) < _MAIL_POLL_EVERY:
                        continue
                    st["last_poll"] = now.timestamp()
                    rule.state = json.dumps(st)
                    db.commit()
                    await _check_mail_rule(db, rule, st)
            except Exception as e:
                log.warning(f"automation rule error ({rule.name or rule.id}): {e}")
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
    first_run = not seen_uids
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
            log.warning(f"automation mail poll failed for {a.email}: {e}")
            continue
        top = max((int(m.get("uid", 0)) for m in msgs), default=0)
        last = int(seen_uids.get(a.id, 0))
        seen_uids[a.id] = max(top, last)
        if first_run:  # don't storm actions for historical mail
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
            await _fire(
                db,
                rule,
                {"tool": tool, "name": tool, "run_id": run_id or "", "dedupe": f"{run_id}:{tool}"},
            )
    except Exception as e:
        log.warning(f"agent_tool automation failed: {e}")
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
            done[path] = 1
            st["done"] = _trim(done)
            rule.state = json.dumps(st)
            db.commit()
            await _fire(
                db,
                rule,
                {"path": path, "tag": tag, "name": path.rsplit("/", 1)[-1], "dedupe": path},
            )
    except Exception as e:
        log.warning(f"doc_tag automation failed: {e}")
    finally:
        db.close()

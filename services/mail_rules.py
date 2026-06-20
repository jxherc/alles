"""mail rules engine + vacation responder (5d). matching + vacation logic are pure;
applying to the cache (markread/mute) is the locally-testable action (IMAP move/label and
the auto-reply send stay best-effort elsewhere)."""

from core.database import CachedMessage


def _field(rule, name, default=""):
    return rule.get(name, default) if isinstance(rule, dict) else getattr(rule, name, default)


def apply_rules(msg, rules):
    """matched actions for one message: [{action, action_arg}] over enabled rules."""
    out = []
    for r in rules:
        if not _field(r, "enabled", True):
            continue
        field = _field(r, "match_field", "from")
        val = (_field(r, "match_value", "") or "").lower()
        hay = (msg.get("from", "") if field == "from" else msg.get("subject", "")).lower()
        if val and val in hay:
            out.append(
                {
                    "action": _field(r, "action", "markread"),
                    "action_arg": _field(r, "action_arg", ""),
                }
            )
    return out


def run_on_cache(db, account_id, rules):
    """apply markread / mute rules over an account's cached messages. returns count applied."""
    n = 0
    for row in db.query(CachedMessage).filter_by(account_id=account_id).all():
        msg = {"from": row.sender or "", "subject": row.subject or ""}
        for act in apply_rules(msg, rules):
            if act["action"] == "markread" and not row.seen:
                row.seen = True
                n += 1
            elif act["action"] == "mute" and not row.muted:
                row.muted = True
                n += 1
    db.commit()
    return n


def vacation_reply_for(sender, vac, state, today):
    """one out-of-office reply per sender per day. returns (reply_or_None, new_state)."""
    state = dict(state or {})
    if not vac.get("enabled"):
        return None, state
    key = (sender or "").strip().lower()
    if not key or state.get(key) == today:
        return None, state
    state[key] = today
    return {
        "to": sender,
        "subject": vac.get("subject") or "Out of office",
        "body": vac.get("body") or "",
    }, state

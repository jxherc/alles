"""mail rules engine + vacation responder (5d, completed 2g). matching + vacation logic are pure;
applying to the cache (markread/mute/label) + enqueuing autoreplies/vacation sends into the outbox
are locally testable against the db."""

from datetime import datetime

from core.database import CachedMessage, ScheduledMail


def _add_label(csv, label):
    """append `label` to a csv label string, lowercased + deduped, order-preserving."""
    label = (label or "").strip().lower()
    seen, out = set(), []
    for t in (csv or "").split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    if label and label not in seen:
        out.append(label)
    return ",".join(out)


def _enqueue(db, account_id, to, subject, body):
    """queue an outbound reply for the existing outbox job to send (send_at=now)."""
    m = ScheduledMail(
        account_id=account_id,
        to=to,
        subject=subject,
        body=body or "",
        send_at=datetime.utcnow().isoformat(),
        status="scheduled",
    )
    db.add(m)
    return m


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
    """apply markread / mute / label / autoreply rules over an account's cached messages.
    returns count applied. label dedupes; autoreply enqueues once per message (autoreplied guard)."""
    n = 0
    for row in db.query(CachedMessage).filter_by(account_id=account_id).all():
        msg = {"from": row.sender or "", "subject": row.subject or ""}
        for act in apply_rules(msg, rules):
            a, arg = act["action"], act.get("action_arg", "")
            if a == "markread" and not row.seen:
                row.seen = True
                n += 1
            elif a == "mute" and not row.muted:
                row.muted = True
                n += 1
            elif a == "label":
                new = _add_label(row.labels, arg)
                if new != (row.labels or ""):
                    row.labels = new
                    n += 1
            elif a == "autoreply" and not row.autoreplied and (row.sender or "").strip():
                subj = row.subject or ""
                subj = subj if subj.lower().startswith("re:") else f"Re: {subj}"
                _enqueue(db, account_id, row.sender, subj, arg)
                row.autoreplied = True
                n += 1
    db.commit()
    return n


def run_vacation(db, account_id, vac, state, today):
    """walk the account's cached senders, enqueue a vacation reply once per sender per day.
    returns (count_enqueued, new_state). caller persists state (settings)."""
    state = dict(state or {})
    n = 0
    seen_senders = []
    for row in db.query(CachedMessage).filter_by(account_id=account_id, folder="INBOX").all():
        if row.sender in seen_senders:
            continue
        seen_senders.append(row.sender)
        reply, state = vacation_reply_for(row.sender, vac, state, today)
        if reply:
            _enqueue(db, account_id, reply["to"], reply["subject"], reply["body"])
            n += 1
    db.commit()
    return n, state


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

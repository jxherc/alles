"""one place that computes the user's "right now" signals from the local apps.

each signal is a small structured fact with a STABLE key, so the consumers (the
home today widget, the morning briefing, the proactive agent) can reshape/dedupe
without each re-running the same queries. pure read - never writes, never rolls.

a signal looks like:
  {category, key, urgency(0..100), title, detail, link, data}
the `key` bakes in the relevant period so the same situation yields the same key
across runs (dedupe), and a new period (next renewal cycle) yields a new key.
"""

from datetime import date, datetime

from core.database import (
    Account,
    Book,
    Budget,
    CachedMessage,
    CalendarEvent,
    DayEvent,
    Habit,
    HabitLog,
    HealthEntry,
    JournalEntry,
    Reminder,
    Subscription,
    Task,
)

CATEGORIES = ("task", "event", "reminder", "sub", "day_event", "habit", "book", "health",
              "budget", "account", "mail", "journal")


def _journal_locked():
    # forward-compat: a future journal/contact family must stay gated behind the
    # passcode, same as services.personal_index. no journal family exists yet.
    from core.settings import load_settings

    return bool(load_settings().get("journal_passcode"))


def _sig(category, key, urgency, title, detail, link, data):
    return {
        "category": category,
        "key": key,
        "urgency": int(urgency),
        "title": title,
        "detail": detail,
        "link": link,
        "data": data,
    }


def _event_occurs_on(e: CalendarEvent, day: date) -> bool:
    """does a (possibly recurring) calendar event land on `day`? canonical copy -
    routes.today re-exports this so existing callers/tests keep working."""
    try:
        start = date.fromisoformat(str(e.start_dt)[:10])
    except ValueError:
        return False
    if start > day:
        return False
    rec = (e.recurrence or "").strip()
    if e.recur_until:
        try:
            if date.fromisoformat(str(e.recur_until)[:10]) < day:
                return False
        except ValueError:
            pass
    if not rec:
        return start == day
    if rec == "daily":
        return True
    if rec == "weekly":
        return start.weekday() == day.weekday()
    if rec == "monthly":
        return start.day == day.day
    return start == day


# -- collectors: one family each, returning a list of signals -----------------

def _tasks(db, today):
    iso = today.isoformat()
    out = []
    for t in db.query(Task).filter(Task.done == False).all():  # noqa: E712
        if not t.due_date:
            continue
        d = str(t.due_date)[:10]
        if d < iso:
            out.append(_sig("task", f"task_overdue:{t.id}", 70 + (15 if t.priority else 0),
                            t.title, f"overdue since {d}", "tasks",
                            {"id": t.id, "title": t.title, "due": d, "priority": t.priority,
                             "overdue": True}))
        elif d == iso:
            out.append(_sig("task", f"task_due:{t.id}", 50 + (15 if t.priority else 0),
                            t.title, "due today", "tasks",
                            {"id": t.id, "title": t.title, "due": d, "priority": t.priority,
                             "overdue": False}))
    return out


def _events(db, today):
    out = []
    iso = today.isoformat()
    for e in db.query(CalendarEvent).all():
        if not _event_occurs_on(e, today):
            continue
        full = str(e.start_dt)
        t = full[11:16] if len(full) > 10 else ""
        timed = (not e.all_day) and bool(t)
        out.append(_sig("event", f"event:{e.id}:{iso}", 40 if timed else 30,
                        e.title, t or "all day", "calendar",
                        {"id": e.id, "title": e.title, "time": "" if e.all_day else t,
                         "all_day": e.all_day, "start_dt": full}))
    return out


def _reminders(db, today):
    out = []
    for r in db.query(Reminder).filter(Reminder.fired == False).all():  # noqa: E712
        if r.trigger_at and r.trigger_at.date() <= today:
            at = r.trigger_at.strftime("%H:%M")
            out.append(_sig("reminder", f"reminder:{r.id}", 60, r.text, f"reminder {at}",
                            "reminders", {"id": r.id, "text": r.text, "at": at}))
    return out


def _subs(db, today):
    from routes.subscriptions import _parse as _sp

    out = []
    for s in db.query(Subscription).filter(Subscription.active == True).all():  # noqa: E712
        try:
            in_days = (_sp(s.next_due) - today).days
        except (TypeError, ValueError):
            continue
        rd = max(0, s.remind_days or 0)
        # emit within the union of what consumers care about: today's 7-day window,
        # the user's own remind_days, and anything overdue (negative in_days).
        if in_days > max(7, rd):
            continue
        if in_days < 0:
            u = 75
        elif in_days <= 2:
            u = 65
        elif in_days <= 7:
            u = 45
        else:
            u = 25
        detail = f"renews in {in_days}d" if in_days >= 0 else f"overdue {-in_days}d"
        out.append(_sig("sub", f"sub_renew:{s.id}:{s.next_due}", u, s.name, detail,
                        "subs",
                        {"id": s.id, "name": s.name, "in_days": in_days, "price": s.price,
                         "currency": s.currency, "remind_days": rd}))
    return out


def _day_events(db, today):
    from routes.days import _occurrence
    from routes.days import _parse as _dp

    out = []
    for ev in db.query(DayEvent).all():
        orig = _dp(ev.date)
        if ev.repeat in ("yearly", "monthly"):
            target, _nth = _occurrence(orig, today, ev.repeat)
        else:
            target = orig
            if target < today:
                continue
        diff = (target - today).days
        if 0 <= diff <= 14:
            u = 60 if diff <= 1 else (45 if diff <= 3 else 20)
            out.append(_sig("day_event", f"day_event:{ev.id}:{target.isoformat()}", u, ev.name,
                            f"in {diff}d", "days", {"id": ev.id, "name": ev.name, "in_days": diff}))
    return out


def _habits(db, today):
    iso = today.isoformat()
    out = []
    for h in db.query(Habit).filter(Habit.archived == False).all():  # noqa: E712
        done = db.query(HabitLog).filter(HabitLog.habit_id == h.id, HabitLog.date == iso).first()
        if not done:
            out.append(_sig("habit", f"habit_gap:{h.id}:{iso}", 30, h.name, "not done today",
                            "habits", {"id": h.id, "name": h.name}))
    return out


def _books(db, today):
    out = []
    for b in db.query(Book).filter(Book.status == "reading").all():
        out.append(_sig("book", f"book_reading:{b.id}", 15, b.title, "currently reading",
                        "books", {"id": b.id, "title": b.title}))
    return out


def _health(db, today):
    w = (
        db.query(HealthEntry)
        .filter(HealthEntry.kind == "weight")
        .order_by(HealthEntry.id.desc())
        .first()
    )
    if not w:
        return []
    unit = f" {w.unit}" if w.unit else ""
    return [_sig("health", f"health_weight:{w.id}", 10, f"weight {w.value:g}{unit}",
                 f"last logged {w.date}", "health",
                 {"kind": "weight", "value": w.value, "unit": w.unit, "date": w.date})]


def _budget(db, today):
    from routes.money import _spending_by_cat

    month = today.strftime("%Y-%m")
    spent = _spending_by_cat(db, month)
    out = []
    for b in db.query(Budget).all():
        lim = b.limit_amt or 0
        if lim <= 0 or spent.get(b.category, 0.0) < lim:
            continue
        used = spent.get(b.category, 0.0)
        u = 70 if used >= lim * 1.5 else 55
        out.append(_sig("budget", f"budget_over:{b.category}:{month}", u,
                        f"{b.category} over budget",
                        f"spent {used:.0f} of {lim:.0f} this month", "money",
                        {"category": b.category, "spent": round(used, 2), "limit": lim,
                         "over": round(used - lim, 2)}))
    return out


def _accounts(db, today):
    from routes.money import _balances

    bal = _balances(db)
    out = []
    for a in db.query(Account).filter(Account.archived == False).all():  # noqa: E712
        thr = a.low_balance or 0
        if thr <= 0:
            continue
        balance = (a.opening or 0.0) + bal.get(a.id, 0.0)
        if balance >= thr:
            continue
        out.append(_sig("account", f"account_low:{a.id}", 70, f"{a.name} balance low",
                        f"{a.currency}{balance:.0f} (under {a.currency}{thr:.0f})", "money",
                        {"id": a.id, "name": a.name, "balance": round(balance, 2),
                         "threshold": thr, "currency": a.currency}))
    return out


def _mail(db, today):
    from core.settings import load_settings
    from services.mail import is_vip

    vips = load_settings().get("mail_vips", [])
    now_iso = datetime.utcnow().isoformat()
    out = []
    rows = (
        db.query(CachedMessage)
        .filter(CachedMessage.seen == False, CachedMessage.muted == False,  # noqa: E712
                CachedMessage.folder == "INBOX")
        .order_by(CachedMessage.date_ts.desc())
        .limit(60)
        .all()
    )
    for m in rows:
        if m.snoozed_until and m.snoozed_until > now_iso:
            continue
        vip = is_vip(m.sender, vips)
        if not (m.flagged or vip):
            continue
        who = (m.sender or "").split("<")[0].strip() or (m.sender or "")
        out.append(_sig("mail", f"mail_important:{m.account_id}:{m.uid}", 60 if vip else 50,
                        f"{'vip' if vip else 'flagged'}: {m.subject or '(no subject)'}",
                        f"from {who}", "mail",
                        {"account_id": m.account_id, "uid": m.uid, "sender": m.sender,
                         "subject": m.subject, "vip": vip}))
        if len(out) >= 5:
            break
    return out


def _journal(db, today):
    if _journal_locked():  # never surface journal activity while it's passcode-locked
        return []
    last = db.query(JournalEntry).order_by(JournalEntry.date.desc()).first()
    if not last or not last.date:  # don't nag someone who has never journaled
        return []
    try:
        gap = (today - date.fromisoformat(str(last.date)[:10])).days
    except ValueError:
        return []
    if gap < 3:
        return []
    return [_sig("journal", f"journal_stale:{last.date}", 25, "journal is getting stale",
                 f"no entry in {gap} days", "journal",
                 {"last_date": last.date, "gap_days": gap})]


_COLLECTORS = {
    "task": _tasks,
    "event": _events,
    "reminder": _reminders,
    "sub": _subs,
    "day_event": _day_events,
    "habit": _habits,
    "book": _books,
    "health": _health,
    "budget": _budget,
    "account": _accounts,
    "mail": _mail,
    "journal": _journal,
}


def gather(db, today=None, *, categories=None) -> list:
    """compute every current signal. `categories` limits the families (None = all).
    pure read - callers that want to roll subscriptions forward must do that
    themselves before calling (today.py does)."""
    today = today or date.today()
    cats = set(categories) if categories else set(CATEGORIES)
    out = []
    for name in CATEGORIES:
        if name in cats:
            out.extend(_COLLECTORS[name](db, today))
    out.sort(key=lambda s: -s["urgency"])
    return out


def by_category(sigs) -> dict:
    g = {}
    for s in sigs:
        g.setdefault(s["category"], []).append(s)
    return g

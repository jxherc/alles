"""one place that computes the user's "right now" signals from the local apps.

each signal is a small structured fact with a STABLE key, so the consumers (the
home today widget, the morning briefing, the proactive agent) can reshape/dedupe
without each re-running the same queries. pure read - never writes, never rolls.

a signal looks like:
  {category, key, urgency(0..100), title, detail, link, data}
the `key` bakes in the relevant period so the same situation yields the same key
across runs (dedupe), and a new period (next renewal cycle) yields a new key.
"""

import json
from datetime import date, datetime, timedelta

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
    SignalSnapshot,
    Subscription,
    Task,
)

CATEGORIES = (
    "task",
    "event",
    "reminder",
    "sub",
    "day_event",
    "habit",
    "book",
    "health",
    "budget",
    "account",
    "mail",
    "journal",
)


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
            out.append(
                _sig(
                    "task",
                    f"task_overdue:{t.id}",
                    70 + (15 if t.priority else 0),
                    t.title,
                    f"overdue since {d}",
                    "tasks",
                    {
                        "id": t.id,
                        "title": t.title,
                        "due": d,
                        "priority": t.priority,
                        "overdue": True,
                    },
                )
            )
        elif d == iso:
            out.append(
                _sig(
                    "task",
                    f"task_due:{t.id}",
                    50 + (15 if t.priority else 0),
                    t.title,
                    "due today",
                    "tasks",
                    {
                        "id": t.id,
                        "title": t.title,
                        "due": d,
                        "priority": t.priority,
                        "overdue": False,
                    },
                )
            )
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
        out.append(
            _sig(
                "event",
                f"event:{e.id}:{iso}",
                40 if timed else 30,
                e.title,
                t or "all day",
                "calendar",
                {
                    "id": e.id,
                    "title": e.title,
                    "time": "" if e.all_day else t,
                    "all_day": e.all_day,
                    "start_dt": full,
                },
            )
        )
    return out


def _reminders(db, today):
    out = []
    for r in db.query(Reminder).filter(Reminder.fired == False).all():  # noqa: E712
        if r.trigger_at and r.trigger_at.date() <= today:
            at = r.trigger_at.strftime("%H:%M")
            out.append(
                _sig(
                    "reminder",
                    f"reminder:{r.id}",
                    60,
                    r.text,
                    f"reminder {at}",
                    "reminders",
                    {"id": r.id, "text": r.text, "at": at},
                )
            )
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
        out.append(
            _sig(
                "sub",
                f"sub_renew:{s.id}:{s.next_due}",
                u,
                s.name,
                detail,
                "subs",
                {
                    "id": s.id,
                    "name": s.name,
                    "in_days": in_days,
                    "price": s.price,
                    "currency": s.currency,
                    "remind_days": rd,
                },
            )
        )
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
            out.append(
                _sig(
                    "day_event",
                    f"day_event:{ev.id}:{target.isoformat()}",
                    u,
                    ev.name,
                    f"in {diff}d",
                    "days",
                    {"id": ev.id, "name": ev.name, "in_days": diff},
                )
            )
    return out


def _habits(db, today):
    iso = today.isoformat()
    out = []
    for h in db.query(Habit).filter(Habit.archived == False).all():  # noqa: E712
        done = db.query(HabitLog).filter(HabitLog.habit_id == h.id, HabitLog.date == iso).first()
        if not done:
            out.append(
                _sig(
                    "habit",
                    f"habit_gap:{h.id}:{iso}",
                    30,
                    h.name,
                    "not done today",
                    "habits",
                    {"id": h.id, "name": h.name},
                )
            )
    return out


def _books(db, today):
    out = []
    for b in db.query(Book).filter(Book.status == "reading").all():
        out.append(
            _sig(
                "book",
                f"book_reading:{b.id}",
                15,
                b.title,
                "currently reading",
                "books",
                {"id": b.id, "title": b.title},
            )
        )
    return out


def _health(db, today):
    w = (
        db.query(HealthEntry)
        .filter(HealthEntry.kind == "weight")
        .order_by(HealthEntry.date.desc(), HealthEntry.id.desc())  # latest by date, not insertion
        .first()
    )
    if not w:
        return []
    unit = f" {w.unit}" if w.unit else ""
    return [
        _sig(
            "health",
            f"health_weight:{w.id}",
            10,
            f"weight {w.value:g}{unit}",
            f"last logged {w.date}",
            "health",
            {"kind": "weight", "value": w.value, "unit": w.unit, "date": w.date},
        )
    ]


def _budget(db, today):
    from routes.money import _spending_by_cat

    month = today.strftime("%Y-%m")
    spent = _spending_by_cat(db, month)
    out = []
    by_tag = None
    for b in db.query(Budget).all():
        lim = b.limit_amt or 0
        if lim <= 0:
            continue
        tag = (getattr(b, "tag", "") or "").strip().lower()
        if tag:  # 2e - tag budget, rolled up through the hierarchy
            if by_tag is None:
                from services.tag_rules import spending_by_tag

                by_tag = spending_by_tag(db, month)
            used = by_tag.get(tag, 0.0)
            if used < lim:
                continue
            key, label = f"budget_over:tag:{tag}:{month}", f"#{tag} over budget"
            data = {"tag": tag, "spent": round(used, 2), "limit": lim, "over": round(used - lim, 2)}
        else:
            used = spent.get(b.category, 0.0)
            if used < lim:
                continue
            key, label = f"budget_over:{b.category}:{month}", f"{b.category} over budget"
            data = {
                "category": b.category,
                "spent": round(used, 2),
                "limit": lim,
                "over": round(used - lim, 2),
            }
        u = 70 if used >= lim * 1.5 else 55
        out.append(
            _sig(
                "budget", key, u, label, f"spent {used:.0f} of {lim:.0f} this month", "money", data
            )
        )
    out.extend(_anomalies(db, today, month, spent))  # 2c - spend spikes + new merchants
    return out


def _anomalies(db, today, month, spent):
    """2c - category spend spikes vs history + first-time merchants. ride the budget family."""
    from services import money_stats

    out = []
    # reuse the spend dict _budget already computed instead of re-scanning transactions
    for a in money_stats.category_anomalies(db, as_of=today, cur=spent):
        out.append(
            _sig(
                "budget",
                f"anomaly:cat:{a['category']}:{month}",
                65,
                f"{a['category']} spending spike",
                f"{a['current']:.0f} this month vs ~{a['baseline']:.0f} usual ({a['ratio']}x)",
                "money",
                a,
            )
        )
    for nm in money_stats.new_merchants(db, as_of=today)[:3]:
        out.append(
            _sig(
                "budget",
                f"anomaly:merchant:{nm['merchant']}:{month}",
                45,
                f"new merchant: {nm['merchant']}",
                f"first time spending here this month ({nm['amount']:.0f})",
                "money",
                nm,
            )
        )
    return out


def _accounts(db, today):
    from routes.money import _balances

    bal = _balances(db)
    out = []
    out.extend(_tax_reminder(db, today))  # 2f - quarterly estimated-tax set-aside (gated)
    for a in db.query(Account).filter(Account.archived == False).all():  # noqa: E712
        thr = a.low_balance or 0
        if thr <= 0:
            continue
        balance = (a.opening or 0.0) + bal.get(a.id, 0.0)
        if balance >= thr:
            continue
        out.append(
            _sig(
                "account",
                f"account_low:{a.id}",
                70,
                f"{a.name} balance low",
                f"{a.currency}{balance:.0f} (under {a.currency}{thr:.0f})",
                "money",
                {
                    "id": a.id,
                    "name": a.name,
                    "balance": round(balance, 2),
                    "threshold": thr,
                    "currency": a.currency,
                },
            )
        )
    return out


def _tax_reminder(db, today):
    from core.settings import load_settings
    from services import income

    cfg = load_settings()
    if not cfg.get("tax_reminders", False):
        return []
    q = income.upcoming_due(today)
    if not q:
        return []
    earned = income.due_quarter_income(db, q)
    if earned <= 0:
        return []
    rate = cfg.get("tax_setaside_rate", 0.25) or 0.25
    aside = round(earned * rate, 2)
    return [
        _sig(
            "account",
            f"tax_quarter:{q['label']}:{q['due']}",
            60,
            f"{q['label']} estimated taxes due {q['due']}",
            f"set aside ~{aside:.0f} ({int(rate * 100)}% of {earned:.0f} earned)",
            "money",
            {
                "quarter": q["label"],
                "due": q["due"],
                "earned": earned,
                "set_aside": aside,
                "rate": rate,
            },
        )
    ]


def _mail(db, today):
    from core.settings import load_settings
    from services.mail import is_vip

    vips = load_settings().get("mail_vips", [])
    now_iso = datetime.utcnow().isoformat()
    out = []
    rows = (
        db.query(CachedMessage)
        .filter(
            CachedMessage.seen == False,
            CachedMessage.muted == False,  # noqa: E712
            CachedMessage.folder == "INBOX",
        )
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
        out.append(
            _sig(
                "mail",
                f"mail_important:{m.account_id}:{m.uid}",
                60 if vip else 50,
                f"{'vip' if vip else 'flagged'}: {m.subject or '(no subject)'}",
                f"from {who}",
                "mail",
                {
                    "account_id": m.account_id,
                    "uid": m.uid,
                    "sender": m.sender,
                    "subject": m.subject,
                    "vip": vip,
                },
            )
        )
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
    return [
        _sig(
            "journal",
            f"journal_stale:{last.date}",
            25,
            "journal is getting stale",
            f"no entry in {gap} days",
            "journal",
            {"last_date": last.date, "gap_days": gap},
        )
    ]


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


# ── history + synthesis (1b) ────────────────────────────────────────────────────────
# NOTE: record_snapshot WRITES - call it only on the periodic proactive path, never from
# gather() (which stays pure + runs on every page load). synthesize() is a pure read.
def record_snapshot(db, sigs, *, keep_days=30, now=None):
    """persist the current signal set as one snapshot, then trim history older than keep_days."""
    now = now or datetime.utcnow()
    n = 0
    for sg in sigs:
        db.add(
            SignalSnapshot(
                ts=now,
                category=sg.get("category", ""),
                key=sg.get("key", ""),
                urgency=int(sg.get("urgency", 0)),
                data=json.dumps(sg.get("data") or {}),
            )
        )
        n += 1
    db.query(SignalSnapshot).filter(SignalSnapshot.ts < now - timedelta(days=keep_days)).delete()
    db.commit()
    return n


def synthesize(db, now=None, *, window_days=14, trend_min_delta=1.0, corr_min_frac=0.5):
    """read recent snapshot history and emit DERIVED signals (trend:<cat>, corr:<a>:<b>) with an
    `explain`. pure read. needs >=2 distinct snapshot times to say anything."""
    now = now or datetime.utcnow()
    rows = (
        db.query(SignalSnapshot)
        .filter(SignalSnapshot.ts >= now - timedelta(days=window_days))
        .all()
    )
    if not rows:
        return []
    snaps = {}  # ts -> {category: count}
    for r in rows:
        snaps.setdefault(r.ts, {})
        snaps[r.ts][r.category] = snaps[r.ts].get(r.category, 0) + 1
    times = sorted(snaps)
    if len(times) < 2:
        return []
    cats = sorted({c for t in times for c in snaps[t]})
    out = []
    # TREND: a category whose mean count in the late half of the window rose vs the early half
    half = len(times) // 2
    early_t, late_t = (times[:half] or times[:1]), times[half:]
    for cat in cats:
        em = sum(snaps[t].get(cat, 0) for t in early_t) / len(early_t)
        lm = sum(snaps[t].get(cat, 0) for t in late_t) / len(late_t)
        delta = lm - em
        if delta >= trend_min_delta:
            out.append(
                {
                    **_sig(
                        "trend",
                        f"trend:{cat}",
                        min(90, 40 + int(delta * 10)),
                        f"{cat} is trending up",
                        f"{cat} signals rose from ~{em:.0f} to ~{lm:.0f} over the last {window_days}d",
                        "",
                        {
                            "delta": round(delta, 2),
                            "from": round(em, 2),
                            "to": round(lm, 2),
                            "cat": cat,
                        },
                    ),
                    "explain": f"the count of {cat} signals climbed across recent snapshots (~{em:.0f} -> ~{lm:.0f}).",
                }
            )
    # CORR: two categories that co-occur in the same snapshots above a fraction of the window
    n_t = len(times)
    need = max(2, int(corr_min_frac * n_t))
    for i in range(len(cats)):
        for j in range(i + 1, len(cats)):
            a, b = cats[i], cats[j]
            both = sum(1 for t in times if snaps[t].get(a, 0) > 0 and snaps[t].get(b, 0) > 0)
            if both >= need and both / n_t >= corr_min_frac:
                out.append(
                    {
                        **_sig(
                            "corr",
                            f"corr:{a}:{b}",
                            min(70, 30 + int(both / n_t * 40)),
                            f"{a} + {b} keep showing up together",
                            f"{a} and {b} co-occurred in {both}/{n_t} recent snapshots",
                            "",
                            {"a": a, "b": b, "both": both, "snapshots": n_t},
                        ),
                        "explain": f"{a} and {b} appeared together in {both} of {n_t} recent snapshots - they may be linked.",
                    }
                )
    out.sort(key=lambda x: -x["urgency"])
    return out

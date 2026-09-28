"""
activity timeline — one reverse-chron feed of what happened across every alles app.

read-time aggregator (NOT an event table): it queries each app's current owner
on request and marks unavailable sources rather than using stale fallback rows.
each row is a typed event {ts, type, app, title, subtitle, view, id} the client
renders into a scrollable "your life, lately" feed. /today is the forward-looking
slice; this is the backward-looking log.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from core.database import (
    CalendarEvent,
    JournalEntry,
    MailAccount,
    Photo,
    SubPayment,
    Subscription,
    Task,
    Transaction,
    get_db,
)
from services import actual_finance

router = APIRouter(prefix="/api")

# which sources to include; the client can filter via ?types=task,money,...
ALL_TYPES = ["journal", "task", "calendar", "money", "mail", "photo", "doc", "agent", "sub"]


def _dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        s = str(v).replace("Z", "")
        return datetime.fromisoformat(s if "T" in s else s[:10])
    except ValueError:
        return None


def _ev(ts, type_, app, title, subtitle="", view="", eid=""):
    d = _dt(ts)
    if not d:
        return None
    return {
        "ts": d.isoformat(),
        "type": type_,
        "app": app,
        "title": title,
        "subtitle": subtitle,
        "view": view,
        "id": eid,
    }


def _finance_events(db, want: set, cutoff, unavailable: set[str]) -> list[dict]:
    wanted = {"money", "sub"} & want
    if not wanted:
        return []
    cutoff_date = cutoff.date().isoformat()
    out = []
    with actual_finance.AUTHORITY_LOCK:
        try:
            canonical = actual_finance.is_canonical(db)
        except actual_finance.ActualFinanceError:
            unavailable.update(wanted)
            return []

        if not canonical:
            if "money" in wanted:
                for txn in db.query(Transaction).filter(Transaction.date >= cutoff_date).all():
                    amount = txn.amount or 0.0
                    sign = "+" if amount >= 0 else "−"
                    out.append(
                        _ev(
                            txn.date,
                            "money",
                            "money",
                            txn.payee or txn.category or "transaction",
                            f"{sign}{abs(amount):.2f}",
                            "money",
                            txn.id,
                        )
                    )
            if "sub" in wanted:
                for sub in db.query(Subscription).all():
                    if sub.last_posted_due and _dt(sub.last_posted_due) >= cutoff:
                        out.append(
                            _ev(
                                sub.last_posted_due,
                                "sub",
                                "subs",
                                sub.name + " renewed",
                                f"{sub.currency}{sub.price:g}",
                                "subs",
                                sub.id,
                            )
                        )
            return [event for event in out if event]

        try:
            actual = actual_finance.inspect(db)
        except actual_finance.ActualFinanceError:
            unavailable.update(wanted)
            return []

        if "money" in wanted:
            try:
                for txn in actual_finance.transactions(db, actual=actual):
                    if str(txn.get("date") or "") < cutoff_date:
                        continue
                    amount = txn["amount"]
                    sign = "+" if amount >= 0 else "−"
                    out.append(
                        _ev(
                            txn["date"],
                            "money",
                            "money",
                            txn.get("payee") or txn.get("category") or "transaction",
                            f"{sign}{abs(amount):.2f}",
                            "money",
                            txn["id"],
                        )
                    )
            except actual_finance.ActualFinanceError:
                unavailable.add("money")
                out = [event for event in out if event and event["type"] != "money"]

        if "sub" in wanted:
            try:
                schedules = {
                    schedule["id"]: schedule
                    for schedule in actual_finance.subscription_schedules(db, actual=actual)
                }
                payments = actual_finance.subscription_payments(db, actual=actual)
                legacy = {sub.id: sub for sub in db.query(Subscription).all()}
                sidecars: dict[str, list[dict]] = {}
                for payment in db.query(SubPayment).all():
                    sidecars.setdefault(payment.sub_id, []).append(
                        {
                            "id": payment.id,
                            "date": payment.date,
                            "amount": float(payment.base_amount_text or payment.amount or 0),
                            "currency": payment.base_currency_code or "",
                            "txn_id": payment.txn_id or "",
                            "source_payment_id": payment.id,
                        }
                    )
                sub_events = []
                for sub_id in sorted(sidecars.keys() | payments.keys()):
                    schedule = schedules.get(sub_id)
                    old = legacy.get(sub_id)
                    if not schedule and not old:
                        continue
                    name = (
                        actual_finance.subscription_display_name(schedule, old)
                        if schedule
                        else old.name
                    )
                    for payment in actual_finance.merge_payment_history(
                        sidecars.get(sub_id, []), payments.get(sub_id, [])
                    ):
                        if str(payment.get("date") or "") < cutoff_date:
                            continue
                        currency = (
                            payment.get("currency")
                            or (schedule or {}).get("currency")
                            or old.currency
                        )
                        sub_events.append(
                            _ev(
                                payment["date"],
                                "sub",
                                "subs",
                                name + " renewed",
                                f"{currency} {payment['amount']:g}",
                                "subs",
                                sub_id,
                            )
                        )
                out.extend(sub_events)
            except actual_finance.ActualFinanceError:
                unavailable.add("sub")
    return [event for event in out if event]


def _aggregate(db, want: set, days: int, unavailable: set[str]) -> list:
    """build the raw (unsorted) event list across every wanted source. shared by
    the feed (/timeline) and the rollup (/timeline/summary) so they never drift."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    out = []

    # respect the journal passcode lock: when a passcode is set, the timeline (which carries no unlock
    # token) must not leak journal mood/content — same "locked = hidden" contract as signals.
    from core.settings import load_settings

    if "journal" in want and not load_settings().get("journal_passcode", ""):
        for j in db.query(JournalEntry).all():
            jd = _dt(j.updated_at or j.created_at)
            if jd and jd >= cutoff:
                preview = (j.content or "").strip().replace("\n", " ")[:80]
                out.append(
                    _ev(
                        jd,
                        "journal",
                        "journal",
                        f"journaled · {j.date}",
                        (j.mood + " " if j.mood else "") + preview,
                        "journal",
                        j.id,
                    )
                )

    if "task" in want:
        for t in db.query(Task).all():
            if t.completed_at and _dt(t.completed_at) >= cutoff:
                out.append(
                    _ev(t.completed_at, "task", "tasks", "✓ " + t.title, "completed", "tasks", t.id)
                )
            elif not t.done and _dt(t.created_at) and _dt(t.created_at) >= cutoff:
                out.append(_ev(t.created_at, "task", "tasks", t.title, "added", "tasks", t.id))

    if "calendar" in want:
        # past occurrences within the window (recurrence-aware, cheap expansion)
        for e in db.query(CalendarEvent).all():
            sd = _dt(e.start_dt)
            if not sd:
                continue
            rec = (e.recurrence or "").strip()
            occs = []
            if not rec:
                if cutoff <= sd <= datetime.now(UTC).replace(tzinfo=None):
                    occs.append(sd)
            else:
                step = {"daily": 1, "weekly": 7, "monthly": 30}.get(rec, 0)
                if step:
                    d = sd
                    guard = 0
                    while d <= datetime.now(UTC).replace(tzinfo=None) and guard < 800:
                        if d >= cutoff:
                            occs.append(d)
                        d = d + timedelta(days=step)
                        guard += 1
            when = "" if e.all_day else str(e.start_dt)[11:16]
            for o in occs[-6:]:
                out.append(
                    _ev(
                        o,
                        "calendar",
                        "calendar",
                        e.title,
                        ("all-day" if e.all_day else when),
                        "calendar",
                        e.id,
                    )
                )

    out.extend(_finance_events(db, want, cutoff, unavailable))

    if "photo" in want:
        for p in (
            db.query(Photo)
            .filter(
                Photo.deleted_at == None,  # noqa: E711
                (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
            )
            .all()
        ):
            pd = _dt(p.taken_at or p.created_at)
            if pd and pd >= cutoff:
                out.append(
                    _ev(pd, "photo", "gallery", p.original_name or "photo", "added", "photos", p.id)
                )

    if "doc" in want:
        try:
            from services.vault_md import _all_md, vault_dir

            root = vault_dir()
            for p in _all_md():
                mt = datetime.fromtimestamp(p.stat().st_mtime, UTC).replace(tzinfo=None)
                if mt >= cutoff:
                    rel = str(p.relative_to(root)).replace("\\", "/")
                    out.append(_ev(mt, "doc", "docs", p.stem, "edited", "wiki", rel))
        except Exception:
            pass

    if "agent" in want:
        try:
            from services.agent_state import list_runs

            for r in list_runs(limit=60):
                fin = _dt(r.get("finished_at") or r.get("updated_at"))
                if fin and fin >= cutoff:
                    steps = len(r.get("tool_steps", []) or [])
                    out.append(
                        _ev(
                            fin,
                            "agent",
                            "aide",
                            f"agent run · {r.get('status', '')}",
                            f"{steps} step{'' if steps == 1 else 's'}",
                            "chat",
                            r.get("id", ""),
                        )
                    )
        except Exception:
            pass

    if "mail" in want:
        try:
            from core.database import CachedMessage

            for a in db.query(MailAccount).all():
                rows = (
                    db.query(CachedMessage)
                    .filter(CachedMessage.account_id == a.id)
                    .order_by(CachedMessage.date_ts.desc())
                    .limit(40)
                    .all()
                )
                for m in rows:
                    md = _dt(m.date)
                    if md and md >= cutoff:
                        frm = m.sender or ""
                        name = frm.split("<")[0].strip(' "') or frm
                        out.append(
                            _ev(
                                md,
                                "mail",
                                "mail",
                                m.subject or "(no subject)",
                                "from " + name,
                                "mail",
                                str(m.uid),
                            )
                        )
        except Exception:
            pass

    return [e for e in out if e]


@router.get("/timeline")
def timeline(
    days: int = Query(30, ge=1, le=365),
    types: str = Query(""),
    q: str = Query(""),
    limit: int = Query(120, ge=1, le=500),
    db: DbSession = Depends(get_db),
):
    want = set(t.strip() for t in types.split(",") if t.strip()) or set(ALL_TYPES)
    unavailable: set[str] = set()
    out = _aggregate(db, want, days, unavailable)
    ql = (q or "").strip().lower()
    if ql:  # text filter over title + subtitle, after aggregation
        out = [
            e
            for e in out
            if ql in (e["title"] or "").lower() or ql in (e["subtitle"] or "").lower()
        ]
    out.sort(key=lambda e: e["ts"], reverse=True)
    return {"events": out[:limit], "types": sorted(want), "partial_sources": sorted(unavailable)}


@router.get("/timeline/summary")
def timeline_summary(
    days: int = Query(30, ge=1, le=365),
    types: str = Query(""),
    db: DbSession = Depends(get_db),
):
    """rollup over the window: per-source counts (desc), total, and the busiest day."""
    want = set(t.strip() for t in types.split(",") if t.strip()) or set(ALL_TYPES)
    unavailable: set[str] = set()
    out = _aggregate(db, want, days, unavailable)
    by_type: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for e in out:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        day = (e["ts"] or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1
    type_rows = sorted(
        ({"type": t, "count": c} for t, c in by_type.items()),
        key=lambda x: (-x["count"], x["type"]),
    )
    busiest = None
    if by_day:
        d, c = max(by_day.items(), key=lambda kv: (kv[1], kv[0]))
        busiest = {"date": d, "count": c}
    return {
        "days": days,
        "total": len(out),
        "by_type": type_rows,
        "busiest": busiest,
        "partial_sources": sorted(unavailable),
    }

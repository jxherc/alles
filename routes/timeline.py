"""
activity timeline — one reverse-chron feed of what happened across every alles app.

read-time aggregator (NOT an event table): it queries the apps' own tables on
each request, so it's always correct and needs no backfill or write-path coupling.
each row is a typed event {ts, type, app, title, subtitle, view, id} the client
renders into a scrollable "your life, lately" feed. /today is the forward-looking
slice; this is the backward-looking log.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from core.database import (
    CalendarEvent,
    JournalEntry,
    MailAccount,
    Photo,
    Subscription,
    Task,
    Transaction,
    get_db,
)

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


@router.get("/timeline")
def timeline(
    days: int = Query(30, ge=1, le=365),
    types: str = Query(""),
    q: str = Query(""),
    limit: int = Query(120, ge=1, le=500),
    db: DbSession = Depends(get_db),
):
    want = set(t.strip() for t in types.split(",") if t.strip()) or set(ALL_TYPES)
    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_d = cutoff.date()
    out = []

    if "journal" in want:
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
                if cutoff <= sd <= datetime.utcnow():
                    occs.append(sd)
            else:
                step = {"daily": 1, "weekly": 7, "monthly": 30}.get(rec, 0)
                if step:
                    d = sd
                    guard = 0
                    while d <= datetime.utcnow() and guard < 800:
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

    if "money" in want:
        for t in db.query(Transaction).filter(Transaction.date >= cutoff_d.isoformat()).all():
            amt = t.amount or 0.0
            sign = "+" if amt >= 0 else "−"
            out.append(
                _ev(
                    t.date,
                    "money",
                    "money",
                    t.payee or t.category or "transaction",
                    f"{sign}{abs(amt):.2f}",
                    "money",
                    t.id,
                )
            )

    if "photo" in want:
        for p in db.query(Photo).all():
            pd = _dt(p.taken_at or p.created_at)
            if pd and pd >= cutoff:
                out.append(
                    _ev(pd, "photo", "gallery", p.original_name or "photo", "added", "photos", p.id)
                )

    if "sub" in want:
        for s in db.query(Subscription).all():
            if s.last_posted_due and _dt(s.last_posted_due) and _dt(s.last_posted_due) >= cutoff:
                out.append(
                    _ev(
                        s.last_posted_due,
                        "sub",
                        "subs",
                        s.name + " renewed",
                        f"{s.currency}{s.price:g}",
                        "subs",
                        s.id,
                    )
                )

    if "doc" in want:
        try:
            from services.vault_md import _all_md, vault_dir

            root = vault_dir()
            for p in _all_md():
                mt = datetime.utcfromtimestamp(p.stat().st_mtime)
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

    out = [e for e in out if e]
    ql = (q or "").strip().lower()
    if ql:  # text filter over title + subtitle, after aggregation
        out = [
            e
            for e in out
            if ql in (e["title"] or "").lower() or ql in (e["subtitle"] or "").lower()
        ]
    out.sort(key=lambda e: e["ts"], reverse=True)
    return {"events": out[:limit], "types": sorted(want)}

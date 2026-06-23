from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from core.database import (
    Book,
    CalendarEvent,
    Contact,
    Habit,
    MailAccount,
    Message,
    Monitor,
    Photo,
    ReadItem,
    Session,
    Subscription,
    Task,
    Transaction,
    get_db,
)

router = APIRouter(prefix="/api")

_LIMIT = 8


def _snip(text: str, ql: str, span: int = 120) -> str:
    idx = text.lower().find(ql)
    start = max(0, idx - 40) if idx >= 0 else 0
    return text[start : start + span].strip().replace("\n", " ")


def _search_vault(q: str, limit: int) -> list[dict]:
    """search the obsidian vault — .md files on disk, by name + content."""
    from services import vault_md

    base = vault_md.vault_dir()
    ql = q.lower()
    out = []
    for p in sorted(base.rglob("*.md")):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            text = p.read_text("utf-8", errors="replace")
        except Exception:
            continue
        if ql in p.stem.lower() or ql in text.lower():
            out.append(
                {
                    "name": p.stem,
                    "path": str(p.relative_to(base)).replace("\\", "/"),
                    "snippet": _snip(text, ql, 100) or (text[:90].strip().replace("\n", " ")),
                }
            )
        if len(out) >= limit:
            break
    return out


# GET /api/search — one search across every alles app
@router.get("/search/fts")
def fts_search(q: str = Query(""), kind: str = "", limit: int = 20, db: DbSession = Depends(get_db)):
    """3i - first-class FTS5 search: phrase ("a b"), negation (a NOT b), prefix (foo*), field-ranked."""
    from services import fts

    fts.ensure(db)
    return {"results": fts.search(db, q, kind=kind or None, limit=limit)}


@router.get("/search")
def search(q: str = Query(""), db: DbSession = Depends(get_db)):
    empty = {
        "chats": [],
        "notes": [],
        "tasks": [],
        "calendar": [],
        "contacts": [],
        "memories": [],
        "mail": [],
        "money": [],
        "subs": [],
        "photos": [],
        "books": [],
        "read": [],
        "habits": [],
        "watch": [],
    }
    if not q.strip():
        return empty

    # escape LIKE wildcards so a query like "100%" or "node_modules" matches
    # literally instead of treating % / _ as wildcards
    pat = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    ql = q.lower()
    res = dict(empty)

    # chats — session names + message bodies
    by_name = (
        db.query(Session)
        .filter(Session.archived == False, Session.name.ilike(pat, escape="\\"))
        .limit(_LIMIT)
        .all()
    )
    seen = {s.id for s in by_name}
    chats = [{"session_id": s.id, "session_name": s.name, "snippet": s.name} for s in by_name]
    for m in db.query(Message).filter(Message.content.ilike(pat, escape="\\")).limit(_LIMIT * 3).all():
        if m.session_id in seen:
            continue
        seen.add(m.session_id)
        s = db.get(Session, m.session_id)
        if s and not s.archived:
            chats.append(
                {"session_id": s.id, "session_name": s.name, "snippet": _snip(m.content, ql)}
            )
    res["chats"] = chats[:_LIMIT]

    # notes — the vault (.md on disk)
    try:
        res["notes"] = _search_vault(q, _LIMIT)
    except Exception:
        res["notes"] = []

    # tasks
    tasks = db.query(Task).filter(Task.title.ilike(pat, escape="\\")).limit(_LIMIT).all()
    res["tasks"] = [{"id": t.id, "title": t.title, "done": bool(t.done)} for t in tasks]

    # calendar
    evs = (
        db.query(CalendarEvent)
        .filter(or_(CalendarEvent.title.ilike(pat, escape="\\"), CalendarEvent.description.ilike(pat, escape="\\")))
        .limit(_LIMIT)
        .all()
    )
    res["calendar"] = [{"id": e.id, "title": e.title, "when": (e.start_dt or "")[:10]} for e in evs]

    # contacts
    cts = (
        db.query(Contact)
        .filter(
            or_(
                Contact.name.ilike(pat, escape="\\"),
                Contact.email.ilike(pat, escape="\\"),
                Contact.phone.ilike(pat, escape="\\"),
                Contact.notes.ilike(pat, escape="\\"),
            )
        )
        .limit(_LIMIT)
        .all()
    )
    res["contacts"] = [
        {"id": c.id, "name": c.name, "snippet": c.email or c.phone or ""} for c in cts
    ]

    # memories — semantic/keyword via the memory store
    try:
        from services.memory_store import search_memories

        res["memories"] = search_memories(q, top_k=_LIMIT)
    except Exception:
        res["memories"] = []

    # money — transactions by payee/category/notes
    txns = (
        db.query(Transaction)
        .filter(
            or_(
                Transaction.payee.ilike(pat, escape="\\"),
                Transaction.category.ilike(pat, escape="\\"),
                Transaction.notes.ilike(pat, escape="\\"),
            )
        )
        .order_by(Transaction.date.desc())
        .limit(_LIMIT)
        .all()
    )
    res["money"] = [
        {
            "id": t.id,
            "payee": t.payee or t.category or "transaction",
            "amount": t.amount,
            "when": (t.date or "")[:10],
        }
        for t in txns
    ]

    # subscriptions — by name/category
    subs = (
        db.query(Subscription)
        .filter(or_(Subscription.name.ilike(pat, escape="\\"), Subscription.category.ilike(pat, escape="\\")))
        .limit(_LIMIT)
        .all()
    )
    res["subs"] = [
        {"id": s.id, "name": s.name, "snippet": f"{s.currency}{s.price:g} · {s.cycle}"}
        for s in subs
    ]

    # photos — by original filename
    photos = (
        db.query(Photo)
        .filter(Photo.original_name.ilike(pat, escape="\\"))
        .order_by(Photo.created_at.desc())
        .limit(_LIMIT)
        .all()
    )
    res["photos"] = [{"id": p.id, "name": p.original_name or p.filename} for p in photos]

    # mail — instant local search over CACHED headers (no slow IMAP round-trip)
    try:
        from services import mail_cache

        mail_hits = []
        for a in db.query(MailAccount).all():
            for m in mail_cache.search(db, a.id, q, limit=_LIMIT):
                m = {**m, "account_id": a.id}
                mail_hits.append(m)
            if len(mail_hits) >= _LIMIT:
                break
        res["mail"] = mail_hits[:_LIMIT]
    except Exception:
        res["mail"] = []

    # books — title or author
    books = (
        db.query(Book)
        .filter(or_(Book.title.ilike(pat, escape="\\"), Book.author.ilike(pat, escape="\\")))
        .limit(_LIMIT)
        .all()
    )
    res["books"] = [
        {"id": b.id, "title": b.title, "author": b.author, "status": b.status} for b in books
    ]

    # read-later — title, site, or stored body text
    items = (
        db.query(ReadItem)
        .filter(
            or_(ReadItem.title.ilike(pat, escape="\\"), ReadItem.site.ilike(pat, escape="\\"), ReadItem.text.ilike(pat, escape="\\"))
        )
        .order_by(ReadItem.added_at.desc())
        .limit(_LIMIT)
        .all()
    )
    res["read"] = [{"id": it.id, "title": it.title, "site": it.site} for it in items]

    # habits — by name
    habits = db.query(Habit).filter(Habit.name.ilike(pat, escape="\\")).limit(_LIMIT).all()
    res["habits"] = [{"id": h.id, "name": h.name} for h in habits]

    # watch — monitors by name or url
    mons = (
        db.query(Monitor)
        .filter(or_(Monitor.name.ilike(pat, escape="\\"), Monitor.url.ilike(pat, escape="\\")))
        .limit(_LIMIT)
        .all()
    )
    res["watch"] = [{"id": m.id, "name": m.name, "url": m.url} for m in mons]

    return res

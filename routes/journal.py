"""
journal — one entry per day. mood, tags, writing prompts, on-this-day, a
streak counter, and an optional AI reflection on what you wrote.
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, JournalEntry

router = APIRouter(prefix="/api")

# rotating writing prompts — pick one by day so it's stable through the day
PROMPTS = [
    "What's one thing that went well today?",
    "What's been on your mind lately?",
    "Describe a small moment you don't want to forget.",
    "What are you grateful for right now?",
    "What drained you today, and what filled you back up?",
    "If today had a title, what would it be?",
    "What's something you're looking forward to?",
    "What did you learn — about anything or anyone?",
    "Who made your day better, and how?",
    "What would you tell yesterday-you if you could?",
    "What's a worry you can put down for tonight?",
    "What did your body need today — did it get it?",
    "What's one tiny win worth celebrating?",
    "What felt hard, and how did you handle it?",
]


def _iso(s) -> str:
    return date.fromisoformat(str(s)[:10]).isoformat()


def _fmt(e: JournalEntry) -> dict:
    return {
        "id": e.id, "date": e.date, "content": e.content or "",
        "mood": e.mood or "", "tags": e.tags or "",
        "words": len((e.content or "").split()),
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "updated_at": e.updated_at.isoformat() if e.updated_at else "",
    }


def _streak(dates: set[str], today: date) -> int:
    """consecutive days with an entry, counting back from today (or yesterday
    if today isn't written yet, so an unwritten today doesn't zero the streak)."""
    n = 0
    cur = today if today.isoformat() in dates else today - timedelta(days=1)
    while cur.isoformat() in dates:
        n += 1
        cur -= timedelta(days=1)
    return n


@router.get("/journal")
def list_entries(month: str = "", limit: int = 60, db: DbSession = Depends(get_db)):
    q = db.query(JournalEntry)
    if month:   # YYYY-MM
        q = q.filter(JournalEntry.date.like(f"{month[:7]}-%"))
    rows = q.order_by(JournalEntry.date.desc()).all()
    all_dates = {r.date for r in rows} if month else {r.date for r in db.query(JournalEntry.date).all()}
    today = date.today()
    return {
        "entries": [_fmt(e) for e in rows[:limit]],
        "stats": {
            "total": db.query(JournalEntry).count(),
            "this_month": sum(1 for d in all_dates if d.startswith(today.isoformat()[:7])),
            "streak": _streak({r.date for r in db.query(JournalEntry.date).all()}, today),
            "wrote_today": today.isoformat() in {r.date for r in db.query(JournalEntry.date).all()},
        },
    }


@router.get("/journal/prompt")
def todays_prompt():
    return {"prompt": PROMPTS[date.today().toordinal() % len(PROMPTS)]}


@router.get("/journal/on-this-day")
def on_this_day(db: DbSession = Depends(get_db)):
    today = date.today()
    mmdd = today.strftime("-%m-%d")
    rows = (db.query(JournalEntry)
            .filter(JournalEntry.date.like(f"%{mmdd}"), JournalEntry.date != today.isoformat())
            .order_by(JournalEntry.date.desc()).all())
    return {"entries": [_fmt(e) for e in rows]}


@router.get("/journal/search")
def search_entries(q: str, db: DbSession = Depends(get_db)):
    ql = (q or "").strip().lower()
    if not ql:
        return {"results": []}
    out = []
    for e in db.query(JournalEntry).order_by(JournalEntry.date.desc()).all():
        c = e.content or ""
        idx = c.lower().find(ql)
        if idx != -1 or ql in (e.tags or "").lower():
            snip = c[:80]
            if idx != -1:
                s = max(0, idx - 40)
                snip = c[s:idx + len(ql) + 40].replace("\n", " ").strip()
            out.append({"date": e.date, "mood": e.mood or "", "snippet": snip})
        if len(out) >= 100:
            break
    return {"results": out}


@router.get("/journal/export")
def export_entries(db: DbSession = Depends(get_db)):
    """all entries as one markdown document."""
    rows = db.query(JournalEntry).order_by(JournalEntry.date.asc()).all()
    parts = ["# Journal\n"]
    for e in rows:
        head = f"## {e.date}"
        if e.mood:
            head += f" {e.mood}"
        parts.append(head)
        if e.tags:
            parts.append(f"*tags: {e.tags}*")
        parts.append((e.content or "").strip() + "\n")
    return {"markdown": "\n".join(parts), "count": len(rows)}


@router.get("/journal/calendar")
def entry_calendar(year: int = 0, db: DbSession = Depends(get_db)):
    """which days have entries + their word counts, for a contribution heatmap."""
    y = year or date.today().year
    rows = db.query(JournalEntry).filter(JournalEntry.date.like(f"{y}-%")).all()
    return {"year": y, "days": {e.date: len((e.content or "").split()) for e in rows}}


@router.get("/journal/{day}")
def get_entry(day: str, db: DbSession = Depends(get_db)):
    try:
        day = _iso(day)
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    e = db.query(JournalEntry).filter(JournalEntry.date == day).first()
    if not e:
        return {"date": day, "content": "", "mood": "", "tags": "", "words": 0, "exists": False}
    out = _fmt(e)
    out["exists"] = True
    return out


class EntryBody(BaseModel):
    content: str = ""
    mood: str = ""
    tags: str = ""


@router.put("/journal/{day}")
def upsert_entry(day: str, body: EntryBody, db: DbSession = Depends(get_db)):
    try:
        day = _iso(day)
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    from core.database import _now
    e = db.query(JournalEntry).filter(JournalEntry.date == day).first()
    if e:
        e.content, e.mood, e.tags = body.content, body.mood.strip()[:40], body.tags.strip()
        e.updated_at = _now()
    else:
        e = JournalEntry(date=day, content=body.content,
                         mood=body.mood.strip()[:40], tags=body.tags.strip())
        db.add(e)
    db.commit(); db.refresh(e)
    return _fmt(e)


@router.delete("/journal/{day}")
def delete_entry(day: str, db: DbSession = Depends(get_db)):
    e = db.query(JournalEntry).filter(JournalEntry.date == str(day)[:10]).first()
    if not e:
        raise HTTPException(404)
    db.delete(e); db.commit()
    return {"ok": True}


@router.post("/journal/{day}/reflect")
async def reflect(day: str, db: DbSession = Depends(get_db)):
    """a short, warm AI reflection on the day's entry. best-effort — needs a model."""
    e = db.query(JournalEntry).filter(JournalEntry.date == str(day)[:10]).first()
    if not e or not (e.content or "").strip():
        raise HTTPException(400, "nothing written for that day yet")
    from core.database import ModelEndpoint
    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep or not ep.models_list():
        raise HTTPException(400, "no model configured")
    from services.llm import simple_complete
    msgs = [
        {"role": "system", "content": (
            "You are a kind, grounded journaling companion. The user shares a diary "
            "entry; respond in 3-4 sentences: reflect back what you notice, gently name "
            "a feeling or pattern, and offer one small encouragement or question. Warm, "
            "not clinical. No lists, no preamble.")},
        {"role": "user", "content": e.content[:6000]},
    ]
    text = await simple_complete(msgs, ep.base_url, ep.api_key, ep.models_list()[0], max_tokens=400)
    return {"reflection": text.strip()}

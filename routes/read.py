"""
read — a read-later archive. save a URL, fetch + store the readable page text (reusing
the research extractor), and search it offline. links don't rot: the text is kept even
if the page later disappears.
"""

import re
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from core.database import ReadFeed, ReadItem, get_db
from services.research.search import fetch_webpage_content

router = APIRouter(prefix="/api")


# ── pure helpers ──────────────────────────────────────────────────────────────
def site_of(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    except ValueError:
        return ""
    if not host or " " in host or "." not in host:  # not a real domain
        return ""
    return host[4:] if host.startswith("www.") else host


def make_excerpt(text: str, n: int = 240) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def read_minutes(text: str) -> int:
    words = len((text or "").split())
    return max(1, round(words / 200))


def _norm_tags(s: str) -> str:
    return ", ".join(t.strip() for t in (s or "").split(",") if t.strip())


def _fmt(it: ReadItem, full: bool = False) -> dict:
    d = {
        "id": it.id,
        "url": it.url,
        "title": it.title,
        "excerpt": it.excerpt,
        "site": it.site,
        "image": it.image,
        "read_minutes": it.read_minutes,
        "added_at": it.added_at.isoformat() if it.added_at else "",
        "read_at": it.read_at,
        "read": bool(it.read_at),
        "fav": it.fav,
        "archived": it.archived,
        "tags": it.tags,
    }
    if full:
        d["text"] = it.text
    return d


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/read")
def list_items(filter: str = "", q: str = "", tag: str = "", db: DbSession = Depends(get_db)):
    query = db.query(ReadItem)
    if filter == "archived":
        query = query.filter(ReadItem.archived == True)  # noqa: E712
    else:
        query = query.filter(ReadItem.archived == False)  # noqa: E712
        if filter == "unread":
            query = query.filter(ReadItem.read_at == "")
        elif filter == "fav":
            query = query.filter(ReadItem.fav == True)  # noqa: E712
    if q:
        like = f"%{q}%"
        query = query.filter(or_(ReadItem.title.ilike(like), ReadItem.text.ilike(like)))
    if tag:
        query = query.filter(ReadItem.tags.ilike(f"%{tag}%"))
    rows = query.order_by(ReadItem.added_at.desc()).all()
    return {"items": [_fmt(r) for r in rows]}


# ── rss/atom feeds — defined before /read/{rid} so "feeds" isn't read as an id ──
class FeedBody(BaseModel):
    url: str


@router.get("/read/feeds")
def list_feeds(db: DbSession = Depends(get_db)):
    rows = db.query(ReadFeed).order_by(ReadFeed.created_at).all()
    return {
        "feeds": [
            {
                "id": f.id,
                "url": f.url,
                "title": f.title,
                "last_checked": f.last_checked.isoformat() if f.last_checked else "",
            }
            for f in rows
        ]
    }


@router.post("/read/feeds")
def add_feed(body: FeedBody, db: DbSession = Depends(get_db)):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    if not url.startswith("http"):
        url = "https://" + url
    if db.query(ReadFeed).filter_by(url=url).first():
        raise HTTPException(400, "feed already added")
    f = ReadFeed(url=url)
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"id": f.id, "url": f.url}


@router.delete("/read/feeds/{fid}")
def delete_feed(fid: str, db: DbSession = Depends(get_db)):
    f = db.get(ReadFeed, fid)
    if not f:
        raise HTTPException(404)
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.post("/read/feeds/refresh")
async def refresh_now():
    from services.read_feeds import refresh_feeds

    await refresh_feeds()
    return {"ok": True}


@router.get("/read/{rid}")
def get_item(rid: str, db: DbSession = Depends(get_db)):
    it = db.get(ReadItem, rid)
    if not it:
        raise HTTPException(404)
    return _fmt(it, full=True)


class SaveBody(BaseModel):
    url: str


@router.post("/read")
def save_item(body: SaveBody, db: DbSession = Depends(get_db)):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    if not url.startswith("http"):
        url = "https://" + url
    res = fetch_webpage_content(url)
    site = site_of(url)
    text = res.get("content", "") if res else ""
    title = (res.get("title") if res else "") or site or url
    it = ReadItem(
        url=url,
        title=title[:300],
        text=text,
        excerpt=make_excerpt(text),
        site=site,
        image=(res.get("og_image", "") if res else ""),
        read_minutes=read_minutes(text),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    try:
        from services import personal_index
        personal_index.index_record(db, "read", it)
    except Exception:
        pass
    return _fmt(it)


class ReadPatch(BaseModel):
    tags: str | None = None
    fav: bool | None = None
    archived: bool | None = None


@router.patch("/read/{rid}")
def patch_item(rid: str, body: ReadPatch, db: DbSession = Depends(get_db)):
    it = db.get(ReadItem, rid)
    if not it:
        raise HTTPException(404)
    if body.tags is not None:
        it.tags = _norm_tags(body.tags)
    if body.fav is not None:
        it.fav = body.fav
    if body.archived is not None:
        it.archived = body.archived
    db.commit()
    try:
        from services import personal_index
        personal_index.index_record(db, "read", it)
    except Exception:
        pass
    return _fmt(it)


@router.post("/read/{rid}/read")
def toggle_read(rid: str, db: DbSession = Depends(get_db)):
    it = db.get(ReadItem, rid)
    if not it:
        raise HTTPException(404)
    it.read_at = "" if it.read_at else datetime.utcnow().isoformat()
    db.commit()
    try:
        from services import personal_index
        personal_index.index_record(db, "read", it)
    except Exception:
        pass
    return {"read": bool(it.read_at), "read_at": it.read_at}


@router.delete("/read/{rid}")
def delete_item(rid: str, db: DbSession = Depends(get_db)):
    it = db.get(ReadItem, rid)
    if not it:
        raise HTTPException(404)
    db.delete(it)
    db.commit()
    try:
        from services import personal_index
        personal_index.remove_record(db, "read", rid)
    except Exception:
        pass
    return {"ok": True}

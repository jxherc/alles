"""Ordinary read-later URL saves shared by the Read screen and Aide."""

import hashlib
import re
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from core.database import ReadCreateReceipt, ReadItem
from services.research.search import fetch_webpage_content


def site_of(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    except ValueError:
        return ""
    if not host or " " in host or "." not in host:
        return ""
    return host[4:] if host.startswith("www.") else host


def make_excerpt(text: str, n: int = 240) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def read_minutes(text: str) -> int:
    words = len((text or "").split())
    return max(1, round(words / 200))


def create_identity(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise HTTPException(400, "request_id must be a canonical UUID")


def _find_request(db: Session, identity: str):
    return (
        db.query(ReadCreateReceipt, ReadItem)
        .outerjoin(ReadItem, ReadItem.id == ReadCreateReceipt.item_id)
        .filter(ReadCreateReceipt.id == identity)
        .populate_existing()
        .first()
    )


def _replay(found, payload_hash: str = "") -> ReadItem:
    if found is None:
        raise HTTPException(404, "saved URL request not found")
    receipt, item = found
    if payload_hash and receipt.payload_hash != payload_hash:
        raise HTTPException(409, "this request already saved a different URL")
    if item is None:
        raise HTTPException(410, "the saved article was deleted; discard this pending save")
    return item


def recover_url(db: Session, request_id: str) -> ReadItem:
    return _replay(_find_request(db, create_identity(request_id)))


def save_url(db: Session, url: str, request_id: str = "") -> ReadItem:
    url = (url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    if not url.startswith("http"):
        url = "https://" + url
    identity = create_identity(request_id) if request_id else ""
    payload_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    if identity:
        found = _find_request(db, identity)
        if found is not None:
            return _replay(found, payload_hash)
        # Do not keep a database read transaction open during URL extraction.
        db.rollback()
    res = fetch_webpage_content(url)
    if identity:
        # Different workers may finish extraction together. Reserve the write
        # before checking again so one request creates exactly one article.
        db.execute(sql_text("BEGIN IMMEDIATE"))
        found = _find_request(db, identity)
        if found is not None:
            return _replay(found, payload_hash)
    site = site_of(url)
    text = res.get("content", "") if res else ""
    title = (res.get("title") if res else "") or site or url
    item = ReadItem(
        url=url,
        title=title[:300],
        text=text,
        excerpt=make_excerpt(text),
        site=site,
        image=(res.get("og_image", "") if res else ""),
        read_minutes=read_minutes(text),
    )
    db.add(item)
    if identity:
        db.flush()
        db.add(ReadCreateReceipt(id=identity, payload_hash=payload_hash, item_id=item.id))
    db.commit()
    db.refresh(item)
    try:
        from services import personal_index

        personal_index.index_record(db, "read", item)
    except Exception:
        pass
    return item

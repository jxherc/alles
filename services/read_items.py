"""Ordinary read-later URL saves shared by the Read screen and Aide."""

import re
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.database import ReadItem
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


def save_url(db: Session, url: str) -> ReadItem:
    url = (url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    if not url.startswith("http"):
        url = "https://" + url
    res = fetch_webpage_content(url)
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
    db.commit()
    db.refresh(item)
    try:
        from services import personal_index

        personal_index.index_record(db, "read", item)
    except Exception:
        pass
    return item

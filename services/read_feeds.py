"""rss/atom feeds for read-later — parse a feed and auto-save new entries as
ReadItems. parse_feed/new_items are pure (unit-tested); refresh_feeds runs in the
background job and does the network + db work."""

import logging
import re
from datetime import UTC, datetime

from defusedxml import ElementTree as ET

log = logging.getLogger("alles.readfeeds")

# strip any DOCTYPE (incl. its internal subset) so a malicious feed can't define entities -
# ElementTree expands internal entities, which makes billion-laughs entity-expansion bombs possible.
_DOCTYPE = re.compile(rb"<!DOCTYPE\b[^>\[]*(\[[\s\S]*?\])?\s*>", re.IGNORECASE)
MAX_FEED_BYTES = 2 * 1024 * 1024


def _tag(el):
    return el.tag.rsplit("}", 1)[-1].lower()


def _strip_doctype(xml):
    raw = xml.encode("utf-8", "replace") if isinstance(xml, str) else xml
    return _DOCTYPE.sub(b"", raw)


def parse_feed(xml) -> dict:
    """parse rss or atom → {title, items:[{title, link}]}. never raises."""
    try:
        raw = xml.strip().encode("utf-8", "replace") if isinstance(xml, str) else bytes(xml)
        if len(raw) > MAX_FEED_BYTES:
            return {"title": "", "items": []}
        root = ET.fromstring(_strip_doctype(raw))
    except Exception:
        return {"title": "", "items": []}

    items = []
    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        title, guid, published, summary, links = "", "", "", "", []
        for c in el:
            ct = _tag(c)
            if ct == "title" and not title:
                title = (c.text or "").strip()
            elif ct in ("guid", "id") and not guid:
                guid = (c.text or "").strip()
            elif ct in ("pubdate", "published", "updated") and not published:
                published = (c.text or "").strip()
            elif ct in ("description", "summary", "content") and not summary:
                summary = " ".join(part.strip() for part in c.itertext() if part.strip())
            elif ct == "link":
                href = c.get("href") or (c.text or "").strip()
                if href:
                    links.append((c.get("rel"), href.strip()))
        link = ""
        for rel, href in links:
            if rel in (None, "alternate"):  # the article URL, not self/enclosure
                link = href
                break
        if not link and links:
            link = links[0][1]
        if link:
            items.append(
                {
                    "title": title or link,
                    "link": link,
                    "guid": guid or link,
                    "published": published,
                    "summary": re.sub(r"<[^>]+>", " ", summary).strip(),
                }
            )

    title = ""
    for el in root.iter():
        if _tag(el) in ("channel", "feed"):
            for c in el:
                if _tag(c) == "title":
                    title = (c.text or "").strip()
                    break
            if title:
                break
    return {"title": title, "items": items}


def new_items(items, existing_urls) -> list:
    """the feed items whose link isn't already saved."""
    ex = set(existing_urls)
    return [it for it in items if it["link"] not in ex]


async def refresh_feeds():
    """poll every feed, save new entries to read-later. called from the job loop."""
    from core.database import ReadFeed, ReadItem, SessionLocal

    db = SessionLocal()
    try:
        feeds = db.query(ReadFeed).all()
        if not feeds:
            return
        seen = {u for (u,) in db.query(ReadItem.url).all()}
        from services.net_guard import safe_get_async

        for feed in feeds:
            try:
                # SSRF guard re-checked on every redirect hop (a feed url could 302 to internal)
                r = await safe_get_async(feed.url, timeout=15)
                parsed = parse_feed(r.text)
            except Exception as e:
                log.warning(f"feed fetch failed {feed.url}: {e}")
                continue
            if parsed["title"] and not feed.title:
                feed.title = parsed["title"][:200]
            fresh = new_items(parsed["items"], seen)
            for it in fresh[:25]:  # cap per poll so a big feed can't flood
                host = ""
                try:
                    from urllib.parse import urlparse

                    host = urlparse(it["link"]).hostname or ""
                except ValueError:
                    pass
                db.add(
                    ReadItem(
                        url=it["link"],
                        title=(it["title"] or it["link"])[:300],
                        site=host[4:] if host.startswith("www.") else host,
                        tags="feed",
                    )
                )
                seen.add(it["link"])
            feed.last_checked = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

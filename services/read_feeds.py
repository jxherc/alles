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


def parse_feed(xml, *, strict=False) -> dict:
    """Parse RSS or Atom; strict refreshes distinguish invalid from empty feeds."""
    try:
        raw = xml.strip().encode("utf-8", "replace") if isinstance(xml, str) else bytes(xml)
        if len(raw) > MAX_FEED_BYTES:
            raise ValueError("feed is too large")
        root = ET.fromstring(_strip_doctype(raw))
        if strict and _tag(root) not in {"rss", "feed", "rdf"}:
            raise ValueError("not an RSS or Atom feed")
    except Exception as error:
        if strict:
            raise ValueError("feed could not be read") from error
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
    from sqlalchemy import text

    from core.database import ReadFeed, ReadItem, SessionLocal
    from services.net_guard import safe_get_async

    db = SessionLocal()
    outcomes = []
    try:
        feeds = db.query(ReadFeed.id, ReadFeed.url).order_by(ReadFeed.created_at).all()
        db.rollback()
        for feed_id, feed_url in feeds:
            outcome = {"id": feed_id, "ok": False, "added": 0}
            error = "could not fetch this feed"
            try:
                # SSRF guard re-checked on every redirect hop (a feed url could 302 to internal)
                r = await safe_get_async(feed_url, timeout=15)
                error = "feed returned an unsuccessful response"
                r.raise_for_status()
                error = "feed is not valid RSS or Atom"
                parsed = parse_feed(r.text, strict=True)
                error = "could not save feed entries"
                # Recheck saved URLs under the write lock after fetching. Manual
                # and scheduled refreshes must not create the same links twice.
                db.execute(text("BEGIN IMMEDIATE"))
                feed = db.get(ReadFeed, feed_id)
                if not feed or feed.url != feed_url:
                    db.rollback()
                    outcome.update(ok=True, skipped=True)
                    outcomes.append(outcome)
                    continue
                seen = {u for (u,) in db.query(ReadItem.url).all()}
                if parsed["title"] and not feed.title:
                    feed.title = parsed["title"][:200]
                added = 0
                for it in new_items(parsed["items"], seen):
                    if it["link"] in seen:
                        continue
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
                    added += 1
                    if added == 25:
                        break
                feed.last_checked = datetime.now(UTC).replace(tzinfo=None)
                db.commit()
                outcome.update(ok=True, added=added)
            except Exception:
                db.rollback()
                outcome["error"] = error
                log.warning("feed refresh failed for %s: %s", feed_id, error)
            outcomes.append(outcome)
    finally:
        db.close()
    failed = sum(not row["ok"] for row in outcomes)
    return {
        "ok": failed == 0,
        "checked": sum(row["ok"] and not row.get("skipped") for row in outcomes),
        "failed": failed,
        "added": sum(row["added"] for row in outcomes),
        "skipped": sum(bool(row.get("skipped")) for row in outcomes),
        "feeds": outcomes,
    }

"""saved-search monitors: re-run a saved Andromeda search on a schedule and keep the new links.

links only. a background run never asks a model, so a watch can't send a query to a remote
model without the owner confirming it, and it costs nothing beyond the search itself.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

log = logging.getLogger("alles.andromeda.watch")

EVERY_HOURS = (0, 6, 24, 168)
MAX_NEW = 30
MAX_SEEN = 500
PER_TICK = 3


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load(text, default):
    try:
        value = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def summary(row) -> dict:
    return {
        "every_hours": int(row.watch_every_hours or 0),
        "checked_at": row.watch_checked_at.isoformat() if row.watch_checked_at else "",
        "next_at": row.watch_next_at.isoformat() if row.watch_next_at else "",
        "new_count": len(_load(row.watch_new_json, [])),
        "error": row.watch_error or "",
    }


def new_links(row) -> list[dict]:
    return _load(row.watch_new_json, [])


def set_watch(row, every_hours: int, now: datetime | None = None) -> None:
    if every_hours not in EVERY_HOURS:
        raise ValueError("watch every 6 hours, daily, weekly, or not at all")
    now = now or _now()
    row.watch_every_hours = every_hours
    row.watch_error = ""
    if not every_hours:
        row.watch_next_at = None
        return
    seen = _load(row.watch_seen_json, [])
    if not seen:
        # the saved results are the starting point: only links after them count as new
        seen = [r.get("url") for r in _load(row.results_json, []) if isinstance(r, dict)]
        row.watch_seen_json = json.dumps([u for u in seen if u][:MAX_SEEN])
    row.watch_next_at = now + timedelta(hours=every_hours)


def mark_seen(row) -> None:
    row.watch_new_json = "[]"


async def check(row, now: datetime | None = None) -> int:
    """one run; returns how many links are new. never raises for a search failure."""
    from services.andromeda import normal_search, parse_query

    now = now or _now()
    request = _load(row.request_json, {})
    every = int(row.watch_every_hours or 0) or 24
    row.watch_checked_at = now
    row.watch_next_at = now + timedelta(hours=every)
    try:
        # "!ai" only switches the overview off; it is not part of what to search for
        query = parse_query(row.query, overview_default=False).query or row.query
        result = await normal_search(
            query, max_results=10, provider=str(request.get("provider") or "")
        )
    except Exception as error:  # a bad run waits for the next slot instead of retrying hot
        row.watch_error = type(error).__name__[:60]
        return 0
    if result.get("status") not in ("ready", "partial"):
        row.watch_error = str(result.get("failure_type") or result.get("status") or "")[:60]
        return 0
    row.watch_error = ""
    seen = _load(row.watch_seen_json, [])
    known = set(seen)
    fresh = []
    for item in result.get("results") or []:
        url = item.get("url")
        if url and url not in known:
            known.add(url)
            seen.append(url)
            fresh.append(
                {
                    "url": url,
                    "title": str(item.get("title") or url)[:300],
                    "snippet": str(item.get("snippet") or "")[:400],
                    "found_at": now.isoformat(),
                }
            )
    if fresh:
        waiting = [*fresh, *_load(row.watch_new_json, [])][:MAX_NEW]
        row.watch_new_json = json.dumps(waiting)
    row.watch_seen_json = json.dumps(seen[-MAX_SEEN:])
    return len(fresh)


async def _tell(row, count: int) -> None:
    from services import notify
    from services.push_delivery import broadcast_result

    links = "link" if count == 1 else "links"
    text = f'{count} new {links} for "{row.query[:120]}"'
    try:
        await broadcast_result(
            {
                "title": "andromeda",
                "body": text,
                "url": f"/?app=andromeda&saved={row.id}",
                "tag": f"andromeda-watch-{row.id}",
            }
        )
    except Exception as error:
        log.warning("watch push failed: %s", type(error).__name__)
    if notify.configured():
        await notify.send(text)


async def run_due(now: datetime | None = None) -> int:
    """the job: check the watches that are due, a few per tick."""
    from core.build_info import afterlife_feature_flags
    from core.database import SessionLocal
    from core.schema import AndromedaSavedSearch

    if not afterlife_feature_flags()["afterlife_andromeda"]:
        return 0
    now = now or _now()
    db = SessionLocal()
    checked = 0
    try:
        rows = (
            db.query(AndromedaSavedSearch)
            .filter(AndromedaSavedSearch.watch_every_hours > 0)
            .filter(AndromedaSavedSearch.watch_next_at <= now)
            .order_by(AndromedaSavedSearch.watch_next_at)
            .limit(PER_TICK)
            .all()
        )
        for row in rows:
            count = await check(row, now)
            db.commit()
            checked += 1
            if count:
                await _tell(row, count)
    finally:
        db.close()
    return checked

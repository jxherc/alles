"""Durable scheduled News collection, clustering, briefs, and optional Jarvis delivery."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.database import (
    NewsBrief,
    NewsConfiguration,
    NewsEntry,
    NewsSource,
    SessionLocal,
)
from services.read_feeds import parse_feed

STARTER_SOURCES = (
    {
        "name": "Rest of World",
        "url": "https://restofworld.org/feed/latest/",
        "category": "technology",
        "language": "en",
        "priority": 1,
    },
    {
        "name": "報導者 The Reporter",
        "url": "https://public.twreporter.org/rss/twreporter-rss.xml",
        "category": "taiwan",
        "language": "zh-Hant",
        "priority": 2,
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "technology",
        "language": "en",
        "priority": 1,
    },
)

CADENCES = {"morning": "08:00", "evening": "18:00", "custom": "08:00"}
SOURCE_SCHEDULES = {"inherit", "six_hours", "daily"}
LANGUAGES = {"en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar", "other"}
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "with",
}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) > 4000:
        raise ValueError("url is too long")
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid url") from exc
    if scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("url must be public http or https")
    rendered_host = f"[{host}]" if ":" in host else host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        rendered_host = f"{rendered_host}:{port}"
    query_parts = []
    for component in parsed.query.split("&") if parsed.query else ():
        encoded_key = component.partition("=")[0]
        key = unquote_plus(encoded_key).lower()
        if key.startswith("utm_") or key in _TRACKING_KEYS:
            continue
        query_parts.append(component)
    query = "&".join(query_parts)
    return urlunsplit((scheme, rendered_host, parsed.path or "/", query, ""))


def _clean_text(value: str, limit: int) -> str:
    text = html.unescape(re.sub(r"\s+", " ", str(value or ""))).strip()
    return text[:limit]


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _json_value(value, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def ensure_defaults(db) -> NewsConfiguration:
    config = db.get(NewsConfiguration, "singleton")
    if config is not None:
        return config
    db.execute(
        sqlite_insert(NewsConfiguration)
        .values(id="singleton")
        .on_conflict_do_nothing(index_elements=[NewsConfiguration.id])
    )
    for item in STARTER_SOURCES:
        db.execute(
            sqlite_insert(NewsSource)
            .values(id=uuid.uuid4().hex, **item, schedule="inherit", enabled=True)
            .on_conflict_do_nothing(index_elements=[NewsSource.url])
        )
    db.commit()
    config = db.get(NewsConfiguration, "singleton")
    if config is None:
        raise RuntimeError("news defaults could not be initialized")
    return config


def _next_run(config: NewsConfiguration, now: datetime | None = None) -> datetime:
    now = now or utc_now()
    try:
        zone = ZoneInfo(config.timezone or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    local_now = now.replace(tzinfo=UTC).astimezone(zone)
    raw_time = config.time_of_day if config.cadence == "custom" else CADENCES[config.cadence]
    try:
        hour, minute = (int(part) for part in raw_time.split(":"))
    except (TypeError, ValueError):
        hour, minute = 8, 0
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC).replace(tzinfo=None)


def public_configuration(db, config: NewsConfiguration | None = None) -> dict:
    from services import jarvis_discord

    config = config or ensure_defaults(db)
    connector = jarvis_discord.get_connection(db)
    return {
        "enabled": bool(config.enabled),
        "cadence": config.cadence,
        "time_of_day": config.time_of_day,
        "timezone": config.timezone,
        "deliver_home": bool(config.deliver_home),
        "deliver_jarvis": bool(config.deliver_jarvis),
        "next_run_at": _iso(config.next_run_at),
        "last_run_at": _iso(config.last_run_at),
        "last_success_at": _iso(config.last_success_at),
        "last_safe_error": config.last_safe_error or "",
        "jarvis": jarvis_discord.news_delivery_status(connector),
    }


def public_source(source: NewsSource) -> dict:
    health = (
        "retry" if source.last_safe_error else "healthy" if source.last_success_at else "untested"
    )
    return {
        "id": source.id,
        "url": source.url,
        "name": source.name or source.url,
        "category": source.category,
        "language": source.language,
        "priority": source.priority,
        "schedule": source.schedule,
        "enabled": bool(source.enabled),
        "health": health,
        "last_checked_at": _iso(source.last_checked_at),
        "last_success_at": _iso(source.last_success_at),
        "last_safe_error": source.last_safe_error or "",
        "next_retry_at": _iso(source.next_retry_at),
        "failure_count": source.failure_count or 0,
    }


def public_brief(brief: NewsBrief | None) -> dict | None:
    if brief is None:
        return None
    return {
        "id": brief.id,
        "status": brief.status,
        "title": brief.title,
        "summary": brief.summary,
        "clusters": _json_value(brief.clusters, []),
        "source_failures": _json_value(brief.source_failures, []),
        "scheduled_for": _iso(brief.scheduled_for),
        "published_at": _iso(brief.published_at),
        "delivered_home": bool(brief.delivered_home),
        "jarvis_delivery_state": brief.jarvis_delivery_state,
    }


def _safe_fetch_error(error: Exception) -> str:
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "source fetch timed out"
    if isinstance(error, ValueError):
        return "source is not publicly reachable"
    return "source fetch failed"


async def test_source(url: str, fetcher=None) -> dict:
    from services.net_guard import safe_get_async

    fetcher = fetcher or safe_get_async
    normalized = canonical_url(url)
    response = await fetcher(normalized, timeout=15)
    if response.status_code < 200 or response.status_code >= 300:
        raise ValueError(f"source returned HTTP {response.status_code}")
    parsed = parse_feed(response.text)
    if not parsed["items"]:
        raise ValueError("no RSS or Atom entries found")
    items = []
    for item in parsed["items"][:3]:
        try:
            item_url = canonical_url(item.get("link"))
        except ValueError:
            continue
        items.append(
            {
                "title": _clean_text(item.get("title"), 300),
                "url": item_url,
                "published": _clean_text(item.get("published"), 100),
            }
        )
    if not items:
        raise ValueError("no valid RSS or Atom entry links found")
    return {
        "url": normalized,
        "title": _clean_text(parsed["title"], 200),
        "items": items,
    }


def _published(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _content_hash(title: str, excerpt: str) -> str:
    normalized = f"{_clean_text(title, 500).lower()}\n{_clean_text(excerpt, 2000).lower()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def _store_entries(db, source: NewsSource, parsed: dict, now: datetime) -> int:
    created = 0
    for item in parsed["items"][:100]:
        try:
            url = canonical_url(item.get("link"))
        except ValueError:
            continue
        title = _clean_text(item.get("title") or url, 300)
        excerpt = _clean_text(item.get("summary"), 1200)
        guid = _clean_text(item.get("guid") or url, 1000)
        content_hash = _content_hash(title, excerpt)
        exists = (
            db.query(NewsEntry.id)
            .filter(
                or_(
                    NewsEntry.canonical_url == url,
                    (NewsEntry.source_id == source.id) & (NewsEntry.content_hash == content_hash),
                    (NewsEntry.source_id == source.id) & (NewsEntry.guid == guid),
                )
            )
            .first()
        )
        if exists:
            continue
        db.add(
            NewsEntry(
                source_id=source.id,
                guid=guid,
                canonical_url=url,
                title=title,
                excerpt=excerpt,
                published_at=_published(item.get("published")),
                content_hash=content_hash,
                fetched_at=now,
            )
        )
        created += 1
    return created


async def _fetch_source(db, source: NewsSource, now: datetime, fetcher) -> dict:
    headers = {}
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified
    source.last_checked_at = now
    try:
        response = await fetcher(source.url, timeout=15, headers=headers)
        if response.status_code == 304:
            created = 0
        else:
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError("bad response")
            parsed = parse_feed(response.text)
            if not parsed["items"]:
                raise RuntimeError("empty feed")
            if parsed["title"] and not source.name:
                source.name = _clean_text(parsed["title"], 200)
            created = _store_entries(db, source, parsed, now)
            source.etag = _clean_text(response.headers.get("etag"), 500)
            source.last_modified = _clean_text(response.headers.get("last-modified"), 500)
        source.last_success_at = now
        source.last_safe_error = ""
        source.next_retry_at = None
        source.failure_count = 0
        return {"source_id": source.id, "ok": True, "created": created}
    except Exception as error:
        source.failure_count = (source.failure_count or 0) + 1
        minutes = min(24 * 60, 5 * (2 ** min(source.failure_count - 1, 8)))
        source.next_retry_at = now + timedelta(minutes=minutes)
        source.last_safe_error = _safe_fetch_error(error)
        return {"source_id": source.id, "ok": False, "error": source.last_safe_error}


def _source_poll_due(source: NewsSource, now: datetime) -> bool:
    if source.next_retry_at:
        return source.next_retry_at <= now
    if not source.last_checked_at:
        return True
    interval = timedelta(hours=6 if source.schedule == "six_hours" else 24)
    return source.schedule != "inherit" and source.last_checked_at + interval <= now


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", str(value or "").lower(), re.UNICODE)
        if token not in _STOPWORDS
    }


def _similar(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= 0.42


def cluster_recent(db, now: datetime | None = None, limit: int = 8) -> list[dict]:
    now = now or utc_now()
    since = now - timedelta(days=3)
    future_limit = now + timedelta(hours=6)
    rows = (
        db.query(NewsEntry, NewsSource)
        .join(NewsSource, NewsSource.id == NewsEntry.source_id)
        .filter(
            NewsSource.enabled.is_(True),
            or_(
                and_(
                    NewsEntry.published_at.isnot(None),
                    NewsEntry.published_at >= since,
                    NewsEntry.published_at <= future_limit,
                ),
                and_(NewsEntry.published_at.is_(None), NewsEntry.fetched_at >= since),
            ),
        )
        .order_by(NewsEntry.published_at.desc(), NewsEntry.fetched_at.desc())
        .limit(240)
        .all()
    )
    groups: list[dict] = []
    for entry, source in rows:
        words = _tokens(entry.title)
        group = next((item for item in groups if _similar(words, item["tokens"])), None)
        if group is None:
            group = {"tokens": words, "items": []}
            groups.append(group)
        else:
            group["tokens"].update(words)
        group["items"].append((entry, source))

    ranked = []
    for group in groups:
        entries = group["items"]
        sources = {source.id for _entry, source in entries}
        newest = max((entry.published_at or entry.fetched_at or since) for entry, _ in entries)
        age_hours = max(0, (now - newest).total_seconds() / 3600)
        priority = max(source.priority or 0 for _entry, source in entries)
        score = priority * 100 + len(sources) * 12 + max(0, 72 - age_hours)
        ranked.append((score, entries))
    ranked.sort(key=lambda item: item[0], reverse=True)

    clusters = []
    for _score, entries in ranked[:limit]:
        entries.sort(key=lambda item: item[0].published_at or item[0].fetched_at, reverse=True)
        representative, representative_source = entries[0]
        key = hashlib.sha256(
            "|".join(sorted(entry.content_hash for entry, _ in entries)).encode()
        ).hexdigest()
        for entry, _source in entries:
            entry.cluster_key = key
        links = [
            {
                "title": entry.title,
                "url": entry.canonical_url,
                "source": source.name or source.url,
                "published_at": _iso(entry.published_at),
            }
            for entry, source in entries[:3]
        ]
        fallback = (
            representative.excerpt
            or f"Coverage from {', '.join(dict.fromkeys(link['source'] for link in links))}."
        )
        clusters.append(
            {
                "key": key,
                "title": representative.title,
                "summary": _clean_text(fallback, 500),
                "category": representative_source.category,
                "links": links,
            }
        )
    return clusters


async def summarize_clusters(db, clusters: list[dict]) -> tuple[list[dict], bool]:
    if not clusters:
        return clusters, False
    try:
        from services.llm import simple_complete
        from services.model_resolver import resolve_model

        selected = resolve_model(db, "jarvis")
        evidence = [
            {
                "index": index,
                "title": cluster["title"],
                "excerpt": cluster["summary"],
                "sources": [link["source"] for link in cluster["links"]],
            }
            for index, cluster in enumerate(clusters)
        ]
        prompt = [
            {
                "role": "system",
                "content": (
                    "Summarize each supplied news cluster in one factual sentence. Use only the supplied "
                    "evidence. Return a JSON array of objects with integer index and string summary."
                ),
            },
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
        ]
        raw = await asyncio.wait_for(
            simple_complete(
                prompt,
                selected.endpoint.base_url,
                selected.endpoint.api_key,
                selected.model,
                max_tokens=900,
            ),
            timeout=50,
        )
        match = re.search(r"\[[\s\S]*\]", raw)
        values = json.loads(match.group(0) if match else raw)
        summaries = {
            int(item["index"]): _clean_text(item["summary"], 500)
            for item in values
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        }
        if not summaries:
            return clusters, False
        for index, cluster in enumerate(clusters):
            if index in summaries:
                cluster["summary"] = summaries[index]
        return clusters, True
    except Exception:
        return clusters, False


async def _retry_pending_summaries(db, *, limit: int = 10) -> int:
    """Retry durable link digests on later publishing runs without losing their fallback."""
    rows = (
        db.query(NewsBrief)
        .filter(NewsBrief.status == "summary_pending")
        .order_by(NewsBrief.created_at)
        .limit(limit)
        .all()
    )
    completed = 0
    for brief in rows:
        clusters = _json_value(brief.clusters, [])
        if not isinstance(clusters, list) or not clusters:
            continue
        clusters, summarized = await summarize_clusters(db, clusters)
        if not summarized:
            continue
        brief.clusters = json.dumps(clusters, ensure_ascii=False)
        brief.summary = (
            " ".join(_clean_text(cluster.get("summary"), 500) for cluster in clusters[:3]).strip()[
                :1200
            ]
            or brief.summary
        )
        brief.status = "ready"
        completed += 1
    if completed:
        db.commit()
    return completed


def _brief_delivery_text(brief: NewsBrief) -> str:
    clusters = _json_value(brief.clusters, [])
    lines = [brief.title]
    for cluster in clusters[:6]:
        links = cluster.get("links") or []
        lines.append(f"• {cluster.get('title', 'story')}")
        if cluster.get("summary"):
            lines.append(_clean_text(cluster["summary"], 500))
        if links:
            lines.append(str(links[0].get("url") or ""))
    if brief.status == "summary_pending":
        lines.append("Link digest ready; summary pending.")
    return "\n".join(lines)[:1900]


async def deliver_pending_briefs(now: datetime | None = None) -> dict:
    from services.jarvis_discord import deliver_news_brief

    now = now or utc_now()
    db = SessionLocal()
    delivered = failed = 0
    try:
        rows = (
            db.query(NewsBrief)
            .filter(
                NewsBrief.jarvis_delivery_state.in_(("pending", "retry", "sending")),
                or_(
                    NewsBrief.jarvis_next_attempt_at.is_(None),
                    NewsBrief.jarvis_next_attempt_at <= now,
                ),
            )
            .order_by(NewsBrief.created_at)
            .limit(10)
            .all()
        )
        for brief in rows:
            claimed = (
                db.query(NewsBrief)
                .filter(
                    NewsBrief.id == brief.id,
                    NewsBrief.jarvis_delivery_state == brief.jarvis_delivery_state,
                    or_(
                        NewsBrief.jarvis_next_attempt_at.is_(None),
                        NewsBrief.jarvis_next_attempt_at <= now,
                    ),
                )
                .update(
                    {
                        NewsBrief.jarvis_delivery_state: "sending",
                        NewsBrief.jarvis_attempt_count: (brief.jarvis_attempt_count or 0) + 1,
                        NewsBrief.jarvis_next_attempt_at: now + timedelta(minutes=30),
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if claimed != 1:
                continue
            db.refresh(brief)
            result = await deliver_news_brief(
                _brief_delivery_text(brief), idempotency_key=f"news-brief:{brief.id}"
            )
            if result == "delivered":
                brief.jarvis_delivery_state = "delivered"
                brief.jarvis_next_attempt_at = None
                delivered += 1
            elif result == "deferred":
                brief.jarvis_delivery_state = "pending"
                brief.jarvis_next_attempt_at = now + timedelta(minutes=30)
            elif result == "unavailable" or brief.jarvis_attempt_count >= 4:
                brief.jarvis_delivery_state = "failed"
                brief.jarvis_next_attempt_at = None
                failed += 1
            else:
                brief.jarvis_delivery_state = "retry"
                brief.jarvis_next_attempt_at = now + timedelta(
                    minutes=5 * (2 ** (brief.jarvis_attempt_count - 1))
                )
            db.commit()
        return {"delivered": delivered, "failed": failed}
    finally:
        db.close()


def _renew_run_claim(db, claim_token: str, *, now: datetime | None = None) -> bool:
    if not claim_token:
        return False
    renewed = (
        db.query(NewsConfiguration)
        .filter(
            NewsConfiguration.id == "singleton",
            NewsConfiguration.run_token == claim_token,
        )
        .update(
            {NewsConfiguration.run_lease_until: (now or utc_now()) + timedelta(minutes=30)},
            synchronize_session=False,
        )
    )
    db.commit()
    return renewed == 1


def _commit_run_schedule(
    db,
    claim_token: str,
    *,
    last_run_at: datetime,
    next_run_at: datetime,
    now: datetime | None = None,
    clear_claim: bool = False,
) -> bool:
    if not claim_token:
        return False
    values = {
        NewsConfiguration.last_run_at: last_run_at,
        NewsConfiguration.next_run_at: next_run_at,
        NewsConfiguration.run_lease_until: (now or utc_now()) + timedelta(minutes=30),
    }
    if clear_claim:
        values.update(
            {
                NewsConfiguration.run_token: "",
                NewsConfiguration.run_lease_until: None,
            }
        )
    updated = (
        db.query(NewsConfiguration)
        .filter(
            NewsConfiguration.id == "singleton",
            NewsConfiguration.run_token == claim_token,
        )
        .update(values, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return False
    db.commit()
    return True


async def run_pipeline(*, force: bool = False, fetcher=None, now: datetime | None = None) -> dict:
    from services.net_guard import safe_get_async

    fetcher = fetcher or safe_get_async
    now = now or utc_now()
    db = SessionLocal()
    claim_token = ""
    try:
        config = ensure_defaults(db)
        if not config.enabled and not force:
            return {"ran": False, "reason": "disabled", "brief": None, "sources": []}
        publish = force or config.next_run_at is None or config.next_run_at <= now
        claimed_next_run = None
        claim_token = uuid.uuid4().hex
        claim_filters = [
            NewsConfiguration.id == config.id,
            or_(
                NewsConfiguration.run_lease_until.is_(None),
                NewsConfiguration.run_lease_until <= now,
            ),
        ]
        if publish:
            observed_next_run = config.next_run_at
            claimed_next_run = _next_run(config, now)
            expected = NewsConfiguration.next_run_at.is_(None)
            if observed_next_run is not None:
                expected = NewsConfiguration.next_run_at == observed_next_run
            claim_filters.append(expected)
        claimed = (
            db.query(NewsConfiguration)
            .filter(*claim_filters)
            .update(
                {
                    NewsConfiguration.run_token: claim_token,
                    NewsConfiguration.run_lease_until: now + timedelta(minutes=30),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed != 1:
            return {"ran": False, "reason": "busy", "brief": None, "sources": []}
        db.refresh(config)
        sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()  # noqa: E712
        results = []
        for source in sources:
            if force or _source_poll_due(source, now) or (publish and not source.next_retry_at):
                results.append(await _fetch_source(db, source, now, fetcher))
                db.commit()
                if not _renew_run_claim(db, claim_token):
                    return {
                        "ran": False,
                        "reason": "lease_lost",
                        "brief": None,
                        "sources": results,
                    }
        if not publish:
            return {"ran": bool(results), "reason": "polled", "brief": None, "sources": results}

        await _retry_pending_summaries(db)
        if not _renew_run_claim(db, claim_token):
            return {
                "ran": False,
                "reason": "lease_lost",
                "brief": None,
                "sources": results,
            }

        failures = [
            {"source_id": source.id, "error": source.last_safe_error}
            for source in sources
            if source.last_safe_error
        ]
        clusters = cluster_recent(db, now)
        if not clusters:
            config.last_safe_error = "no recent stories were available"
            if not _commit_run_schedule(
                db,
                claim_token,
                last_run_at=now,
                next_run_at=claimed_next_run,
                now=now,
                clear_claim=True,
            ):
                return {
                    "ran": False,
                    "reason": "lease_lost",
                    "brief": None,
                    "sources": results,
                }
            return {"ran": True, "reason": "empty", "brief": None, "sources": results}

        clusters, summarized = await summarize_clusters(db, clusters)
        if not _renew_run_claim(db, claim_token):
            return {
                "ran": False,
                "reason": "lease_lost",
                "brief": None,
                "sources": results,
            }
        status = "ready" if summarized else "summary_pending"
        summary = " ".join(
            _clean_text(cluster.get("summary"), 500) for cluster in clusters[:3]
        ).strip()[:1200]
        brief = NewsBrief(
            status=status,
            title=f"news brief · {now:%b %d}",
            summary=summary
            or (
                f"{len(clusters)} reviewed topic{'s' if len(clusters) != 1 else ''} from "
                f"{len({link['source'] for cluster in clusters for link in cluster['links']})} sources."
            ),
            clusters=json.dumps(clusters, ensure_ascii=False),
            source_failures=json.dumps(failures),
            scheduled_for=now,
            published_at=now,
            delivered_home=bool(config.deliver_home),
            jarvis_delivery_state="pending" if config.deliver_jarvis else "off",
        )
        db.add(brief)
        config.last_success_at = now
        config.last_safe_error = "" if not failures else "one or more sources will retry"
        if not _commit_run_schedule(
            db,
            claim_token,
            last_run_at=now,
            next_run_at=claimed_next_run,
            now=now,
            clear_claim=True,
        ):
            return {
                "ran": False,
                "reason": "lease_lost",
                "brief": None,
                "sources": results,
            }
        db.refresh(brief)
        result = {
            "ran": True,
            "reason": "published",
            "brief": public_brief(brief),
            "sources": results,
        }
    finally:
        if claim_token:
            try:
                db.query(NewsConfiguration).filter(
                    NewsConfiguration.id == "singleton",
                    NewsConfiguration.run_token == claim_token,
                ).update(
                    {
                        NewsConfiguration.run_token: "",
                        NewsConfiguration.run_lease_until: None,
                    },
                    synchronize_session=False,
                )
                db.commit()
            except Exception:
                db.rollback()
        db.close()
    return result


async def run_due_news() -> dict:
    result = await run_pipeline()
    deliveries = await deliver_pending_briefs()
    return {**result, "deliveries": deliveries}

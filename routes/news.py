"""Owner-facing API for first-class scheduled News."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.auth import require_auth
from core.database import NewsBrief, NewsEntry, NewsSource, get_db
from services import news

router = APIRouter(prefix="/api/news", tags=["news"], dependencies=[Depends(require_auth)])


def _time(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError as error:
        raise HTTPException(400, "time must use HH:MM") from error
    return parsed.strftime("%H:%M")


def _timezone(value: str) -> str:
    raw = str(value or "").strip()
    try:
        ZoneInfo(raw)
    except Exception as error:
        raise HTTPException(400, "unknown timezone") from error
    return raw


def _source_values(values: dict) -> dict:
    output = {}
    if "url" in values:
        try:
            output["url"] = news.canonical_url(values["url"])
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
    if "name" in values:
        output["name"] = str(values["name"] or "").strip()[:200]
    if "category" in values:
        category = str(values["category"] or "general").strip().lower()[:60]
        output["category"] = category or "general"
    if "language" in values:
        language = str(values["language"] or "").strip()
        if language not in news.LANGUAGES:
            raise HTTPException(400, "unsupported language")
        output["language"] = language
    if "priority" in values:
        if values["priority"] is None:
            raise HTTPException(400, "priority cannot be null")
        priority = int(values["priority"])
        if priority not in {0, 1, 2, 3}:
            raise HTTPException(400, "priority must be between 0 and 3")
        output["priority"] = priority
    if "schedule" in values:
        schedule = str(values["schedule"] or "")
        if schedule not in news.SOURCE_SCHEDULES:
            raise HTTPException(400, "unsupported source schedule")
        output["schedule"] = schedule
    if "enabled" in values:
        if values["enabled"] is None:
            raise HTTPException(400, "enabled cannot be null")
        output["enabled"] = bool(values["enabled"])
    return output


def _state(db: DbSession) -> dict:
    config = news.ensure_defaults(db)
    latest = db.query(NewsBrief).order_by(NewsBrief.published_at.desc()).first()
    sources = db.query(NewsSource).order_by(NewsSource.priority.desc(), NewsSource.name).all()
    return {
        "configuration": news.public_configuration(db, config),
        "sources": [news.public_source(source) for source in sources],
        "latest_brief": news.public_brief(latest),
    }


@router.get("")
def get_news(db: DbSession = Depends(get_db)):
    return _state(db)


class ConfigurationPatch(BaseModel):
    enabled: bool | None = None
    cadence: str | None = None
    time_of_day: str | None = None
    timezone: str | None = None
    deliver_home: bool | None = None
    deliver_jarvis: bool | None = None


@router.patch("/configuration")
def patch_configuration(body: ConfigurationPatch, db: DbSession = Depends(get_db)):
    config = news.ensure_defaults(db)
    values = body.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(400, "configuration fields cannot be null")
    if "cadence" in values and values["cadence"] not in news.CADENCES:
        raise HTTPException(400, "unsupported cadence")
    if "time_of_day" in values:
        values["time_of_day"] = _time(values["time_of_day"])
    if "timezone" in values:
        values["timezone"] = _timezone(values["timezone"])
    if values.get("deliver_jarvis"):
        readiness = news.public_configuration(db, config)["jarvis"]
        if not readiness["available"]:
            raise HTTPException(409, readiness["reason"] or "Jarvis is unavailable")
    for key, value in values.items():
        setattr(config, key, value)
    if config.enabled:
        config.next_run_at = news._next_run(config)
    else:
        config.next_run_at = None
    if values.get("deliver_jarvis") is False:
        db.query(NewsBrief).filter(
            NewsBrief.jarvis_delivery_state.in_(("pending", "retry"))
        ).update({"jarvis_delivery_state": "off", "jarvis_next_attempt_at": None})
    db.commit()
    return news.public_configuration(db, config)


class SourceTestBody(BaseModel):
    url: str


@router.post("/sources/test")
async def test_source(body: SourceTestBody):
    try:
        return await news.test_source(body.url)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(502, "source could not be checked safely") from error


class SourceBody(BaseModel):
    url: str
    name: str = ""
    category: str = "general"
    language: str = "en"
    priority: int = 1
    schedule: str = "inherit"
    enabled: bool = True


@router.post("/sources")
def create_source(body: SourceBody, db: DbSession = Depends(get_db)):
    news.ensure_defaults(db)
    source = NewsSource(**_source_values(body.model_dump()))
    db.add(source)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "source already exists") from error
    db.refresh(source)
    return news.public_source(source)


class SourcePatch(BaseModel):
    url: str | None = None
    name: str | None = None
    category: str | None = None
    language: str | None = None
    priority: int | None = None
    schedule: str | None = None
    enabled: bool | None = None


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch, db: DbSession = Depends(get_db)):
    source = db.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    for key, value in _source_values(body.model_dump(exclude_unset=True)).items():
        setattr(source, key, value)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "source already exists") from error
    db.refresh(source)
    return news.public_source(source)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, db: DbSession = Depends(get_db)):
    source = db.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    db.query(NewsEntry).filter(NewsEntry.source_id == source_id).delete()
    db.delete(source)
    db.commit()
    return {"ok": True}


@router.post("/run")
async def run_now(db: DbSession = Depends(get_db)):
    config = news.ensure_defaults(db)
    if not config.enabled:
        raise HTTPException(409, "enable News before running a brief")
    result = await news.run_pipeline(force=True)
    result["deliveries"] = await news.deliver_pending_briefs()
    return result


@router.get("/briefs")
def list_briefs(limit: int = 20, db: DbSession = Depends(get_db)):
    safe_limit = max(1, min(limit, 100))
    rows = (
        db.query(NewsBrief)
        .order_by(NewsBrief.published_at.desc(), NewsBrief.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    return {"briefs": [news.public_brief(row) for row in rows]}


@router.get("/briefs/latest")
def latest_brief(db: DbSession = Depends(get_db)):
    row = db.query(NewsBrief).order_by(NewsBrief.published_at.desc()).first()
    return {"brief": news.public_brief(row)}


@router.post("/briefs/{brief_id}/retry-jarvis")
async def retry_jarvis(brief_id: str, db: DbSession = Depends(get_db)):
    brief = db.get(NewsBrief, brief_id)
    if brief is None:
        raise HTTPException(404, "brief not found")
    readiness = news.public_configuration(db)["jarvis"]
    if not readiness["available"]:
        raise HTTPException(409, readiness["reason"] or "Jarvis is unavailable")
    brief.jarvis_delivery_state = "retry"
    brief.jarvis_next_attempt_at = None
    db.commit()
    return await news.deliver_pending_briefs()

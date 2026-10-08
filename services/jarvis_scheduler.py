"""Lease-safe Jarvis scheduling, retry, and heartbeat primitives."""

import hashlib
import inspect
import math
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import JarvisRun, JarvisRunEvent, JarvisTrigger, JarvisWorkflow, SessionLocal
from services.jarvis_store import append_event, create_run, json_value, transition_run

_HEARTBEAT_PROBES: dict[str, object] = {}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _parse_datetime(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("invalid_trigger_datetime") from exc
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid_trigger_timezone") from exc
    return _as_utc_naive(parsed)


def _parse_clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("invalid_schedule_time") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError("invalid_schedule_time")
    return parsed


def validate_trigger_config(kind: str, config: dict, timezone_name: str) -> None:
    if not isinstance(config, dict):
        raise ValueError("invalid_trigger_config")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_trigger_timezone") from exc
    if kind == "once":
        _parse_datetime(config.get("at", ""), timezone_name)
    elif kind == "schedule":
        _parse_clock(config.get("time", ""))
        weekdays = config.get("weekdays", list(range(7)))
        if not isinstance(weekdays, list) or not weekdays:
            raise ValueError("invalid_schedule_weekdays")
        if any(not isinstance(day, int) or day < 0 or day > 6 for day in weekdays):
            raise ValueError("invalid_schedule_weekdays")
    elif kind in {"interval", "heartbeat"}:
        seconds = config.get("every_seconds")
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise ValueError("invalid_trigger_interval")
        if seconds < 5 or seconds > 366 * 24 * 3600:
            raise ValueError("invalid_trigger_interval")
        if config.get("anchor"):
            _parse_datetime(config["anchor"], timezone_name)
    quiet_hours = config.get("quiet_hours")
    if quiet_hours is not None:
        if not isinstance(quiet_hours, dict):
            raise ValueError("invalid_quiet_hours")
        try:
            _parse_clock(quiet_hours.get("start", ""))
            _parse_clock(quiet_hours.get("end", ""))
        except ValueError as exc:
            raise ValueError("invalid_quiet_hours") from exc
    for key in ("skip_when_busy", "only_notify_when_useful"):
        if key in config and not isinstance(config[key], bool):
            raise ValueError("invalid_trigger_policy")
    if "cost_limit" in config:
        cost_limit = config["cost_limit"]
        if (
            not isinstance(cost_limit, (int, float))
            or isinstance(cost_limit, bool)
            or not math.isfinite(cost_limit)
            or cost_limit < 0
        ):
            raise ValueError("invalid_cost_limit")


def next_daily_occurrence(
    after_utc: datetime,
    clock: str,
    timezone_name: str,
    weekdays: list[int] | None = None,
) -> datetime:
    zone = ZoneInfo(timezone_name)
    after = _as_utc_naive(after_utc).replace(tzinfo=UTC)
    local_after = after.astimezone(zone)
    local_clock = _parse_clock(clock)
    allowed = set(range(7) if weekdays is None else weekdays)
    for offset in range(370):
        local_date = local_after.date() + timedelta(days=offset)
        if local_date.weekday() not in allowed:
            continue
        naive = datetime.combine(local_date, local_clock)
        candidate = naive.replace(tzinfo=zone, fold=0)
        utc_candidate = candidate.astimezone(UTC)
        # A nonexistent DST wall time does not round-trip. Skip it instead of silently shifting.
        if utc_candidate.astimezone(zone).replace(tzinfo=None) != naive:
            continue
        if utc_candidate > after:
            return utc_candidate.replace(tzinfo=None)
    raise ValueError("schedule_has_no_next_occurrence")


def _next_interval(after: datetime, seconds: float, anchor: datetime | None = None) -> datetime:
    anchor = anchor or after
    if anchor > after:
        return anchor
    steps = math.floor((after - anchor).total_seconds() / seconds) + 1
    return anchor + timedelta(seconds=steps * seconds)


def next_for_trigger(trigger: JarvisTrigger, after: datetime) -> datetime | None:
    config = json_value(trigger.config, dict)
    validate_trigger_config(trigger.kind, config, trigger.timezone or "UTC")
    after = _as_utc_naive(after)
    if trigger.kind == "once":
        return _parse_datetime(config["at"], trigger.timezone or "UTC")
    if trigger.kind == "schedule":
        return next_daily_occurrence(
            after,
            config["time"],
            trigger.timezone or "UTC",
            config.get("weekdays"),
        )
    if trigger.kind in {"interval", "heartbeat"}:
        anchor = (
            _parse_datetime(config["anchor"], trigger.timezone or "UTC")
            if config.get("anchor")
            else None
        )
        return _next_interval(after, float(config["every_seconds"]), anchor)
    return None


def occurrence_key(trigger_id: str, scheduled_for: datetime) -> str:
    value = f"{trigger_id}:{_as_utc_naive(scheduled_for).isoformat(timespec='microseconds')}"
    return hashlib.sha256(value.encode()).hexdigest()


def enqueue_occurrence(
    db: DbSession,
    trigger: JarvisTrigger,
    scheduled_for: datetime,
) -> tuple[JarvisRun, bool]:
    key = occurrence_key(trigger.id, scheduled_for)
    existing = db.query(JarvisRun).filter_by(trigger_id=trigger.id, occurrence_key=key).first()
    if existing:
        return existing, False
    workflow = db.get(JarvisWorkflow, trigger.workflow_id)
    if not workflow:
        raise ValueError("workflow_missing")
    try:
        with db.begin_nested():
            run = create_run(
                db,
                workflow,
                trigger_id=trigger.id,
                scheduled_for=_as_utc_naive(scheduled_for),
                occurrence_key=key,
            )
            db.flush()
            if workflow.concurrency_mode == "skip" and workflow.active_run_id:
                transition_run(
                    db,
                    run,
                    "cancelled",
                    failure_class="busy",
                    safe_error="the workflow was already running",
                )
        return run, True
    except IntegrityError:
        existing = db.query(JarvisRun).filter_by(trigger_id=trigger.id, occurrence_key=key).one()
        return existing, False


def register_heartbeat_probe(trigger_id: str, probe) -> None:
    _HEARTBEAT_PROBES[trigger_id] = probe


def unregister_heartbeat_probe(trigger_id: str) -> None:
    _HEARTBEAT_PROBES.pop(trigger_id, None)


def record_heartbeat(
    db: DbSession,
    trigger: JarvisTrigger,
    fingerprint: str | None,
    checked_at: datetime,
) -> tuple[JarvisRun | None, bool]:
    if trigger.kind != "heartbeat":
        raise ValueError("not_a_heartbeat")
    value = str(fingerprint or "")[:256]
    changed = bool(value and value != (trigger.fingerprint or ""))
    run = None
    created = False
    if changed:
        run, created = enqueue_occurrence(db, trigger, checked_at)
        trigger.fingerprint = value
    trigger.last_run_at = checked_at
    trigger.next_run_at = next_for_trigger(trigger, checked_at)
    return run, created


async def scan_due(now: datetime | None = None) -> dict:
    now = _as_utc_naive(now or utc_now())
    db = SessionLocal()
    created = 0
    missed = 0
    unchanged = 0
    try:
        triggers = (
            db.query(JarvisTrigger)
            .filter(
                JarvisTrigger.enabled.is_(True),
                JarvisTrigger.next_run_at.is_not(None),
                JarvisTrigger.next_run_at <= now,
            )
            .order_by(JarvisTrigger.next_run_at, JarvisTrigger.id)
            .all()
        )
        for trigger in triggers:
            workflow = db.get(JarvisWorkflow, trigger.workflow_id)
            if not workflow or not workflow.enabled:
                continue
            due = trigger.next_run_at
            if trigger.kind == "once":
                grace = max(
                    0, min(int(json_value(trigger.config, dict).get("grace_seconds", 300)), 86400)
                )
                run, was_created = enqueue_occurrence(db, trigger, due)
                if (now - due).total_seconds() > grace:
                    if was_created:
                        transition_run(
                            db,
                            run,
                            "cancelled",
                            failure_class="missed",
                            safe_error="the one-time schedule was outside its grace window",
                        )
                        missed += 1
                else:
                    created += int(was_created)
                trigger.enabled = False
                trigger.next_run_at = None
                trigger.last_run_at = now
                continue
            if trigger.kind == "heartbeat":
                probe = _HEARTBEAT_PROBES.get(trigger.id)
                fingerprint = probe() if probe else None
                if inspect.isawaitable(fingerprint):
                    fingerprint = await fingerprint
                _run, was_created = record_heartbeat(db, trigger, fingerprint, now)
                created += int(was_created)
                unchanged += int(not was_created)
                continue
            _run, was_created = enqueue_occurrence(db, trigger, due)
            created += int(was_created)
            trigger.last_run_at = now
            trigger.next_run_at = next_for_trigger(trigger, now)
        db.commit()
        return {"created": created, "missed": missed, "unchanged": unchanged}
    finally:
        db.close()


def claim_next(
    db: DbSession,
    worker_id: str,
    *,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> JarvisRun | None:
    if not worker_id or lease_seconds < 5 or lease_seconds > 3600:
        raise ValueError("invalid_lease")
    now = _as_utc_naive(now or utc_now())
    candidates = (
        db.query(JarvisRun.id)
        .filter(
            JarvisRun.state == "queued",
            or_(JarvisRun.next_attempt_at.is_(None), JarvisRun.next_attempt_at <= now),
        )
        .order_by(JarvisRun.scheduled_for, JarvisRun.created_at)
        .limit(20)
        .all()
    )
    for (run_id,) in candidates:
        candidate = db.get(JarvisRun, run_id)
        workflow = db.get(JarvisWorkflow, candidate.workflow_id) if candidate else None
        if not workflow or not workflow.enabled:
            continue
        workflow_claimed = False
        if workflow.concurrency_mode != "parallel":
            workflow_claimed = (
                db.query(JarvisWorkflow)
                .filter(
                    JarvisWorkflow.id == workflow.id,
                    JarvisWorkflow.active_run_id.is_(None),
                )
                .update(
                    {JarvisWorkflow.active_run_id: run_id},
                    synchronize_session=False,
                )
                == 1
            )
            if not workflow_claimed:
                continue
        changed = (
            db.query(JarvisRun)
            .filter(
                JarvisRun.id == run_id,
                JarvisRun.state == "queued",
                or_(JarvisRun.next_attempt_at.is_(None), JarvisRun.next_attempt_at <= now),
            )
            .update(
                {
                    JarvisRun.state: "running",
                    JarvisRun.lease_owner: worker_id,
                    JarvisRun.lease_expires_at: now + timedelta(seconds=lease_seconds),
                    JarvisRun.started_at: func.coalesce(JarvisRun.started_at, now),
                    JarvisRun.updated_at: now,
                    JarvisRun.attempt_count: JarvisRun.attempt_count + 1,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            if workflow_claimed:
                db.query(JarvisWorkflow).filter_by(id=workflow.id, active_run_id=run_id).update(
                    {JarvisWorkflow.active_run_id: None}, synchronize_session=False
                )
            continue
        db.flush()
        db.expire_all()
        run = db.get(JarvisRun, run_id)
        append_event(db, run, "lease_claimed", summary="run claimed", data={"worker": worker_id})
        return run
    return None


def renew_lease(
    db: DbSession,
    run_id: str,
    worker_id: str,
    *,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> bool:
    if not worker_id or lease_seconds < 5 or lease_seconds > 3600:
        raise ValueError("invalid_lease")
    now = _as_utc_naive(now or utc_now())
    changed = (
        db.query(JarvisRun)
        .filter_by(id=run_id, state="running", lease_owner=worker_id)
        .update(
            {
                JarvisRun.lease_expires_at: now + timedelta(seconds=lease_seconds),
                JarvisRun.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    return changed == 1


def reclaim_stale_leases(db: DbSession, *, now: datetime | None = None) -> dict:
    now = _as_utc_naive(now or utc_now())
    reclaimed = 0
    uncertain = 0
    rows = (
        db.query(JarvisRun)
        .filter(
            JarvisRun.state == "running",
            JarvisRun.lease_expires_at.is_not(None),
            JarvisRun.lease_expires_at <= now,
        )
        .all()
    )
    for run in rows:
        latest_effect = (
            db.query(JarvisRunEvent)
            .filter(
                JarvisRunEvent.run_id == run.id,
                JarvisRunEvent.kind.in_({"side_effect_started", "side_effect_confirmed"}),
            )
            .order_by(JarvisRunEvent.sequence.desc())
            .first()
        )
        if latest_effect and latest_effect.kind == "side_effect_started":
            transition_run(
                db,
                run,
                "uncertain",
                failure_class="uncertain",
                safe_error="a leased run stopped during an unconfirmed outside action",
            )
            uncertain += 1
        else:
            old_worker = run.lease_owner
            transition_run(db, run, "queued", failure_class="interrupted")
            run.lease_owner = ""
            run.lease_expires_at = None
            append_event(
                db,
                run,
                "lease_reclaimed",
                summary="stale lease reclaimed",
                data={"worker": old_worker},
            )
            reclaimed += 1
        run.lease_owner = ""
        run.lease_expires_at = None
        if run.workflow_id:
            db.query(JarvisWorkflow).filter_by(id=run.workflow_id, active_run_id=run.id).update(
                {JarvisWorkflow.active_run_id: None}, synchronize_session=False
            )
    active = db.query(JarvisWorkflow).filter(JarvisWorkflow.active_run_id.is_not(None)).all()
    for workflow in active:
        claimed = db.get(JarvisRun, workflow.active_run_id)
        if not claimed or claimed.state != "running":
            workflow.active_run_id = None
    return {"reclaimed": reclaimed, "uncertain": uncertain}


def record_failure(
    db: DbSession,
    run: JarvisRun,
    worker_id: str,
    classification: str,
    safe_error: str,
    *,
    now: datetime | None = None,
    max_attempts: int = 3,
    base_backoff_seconds: int = 5,
) -> JarvisRun:
    if run.state != "running" or run.lease_owner != worker_id:
        raise ValueError("lease_not_owned")
    if classification not in {"transient", "permanent", "uncertain"}:
        raise ValueError("invalid_failure_class")
    now = _as_utc_naive(now or utc_now())
    if classification == "transient" and run.attempt_count < max_attempts:
        delay = min(3600, base_backoff_seconds * (2 ** max(0, run.attempt_count - 1)))
        transition_run(db, run, "queued", failure_class="transient", safe_error=safe_error)
        run.next_attempt_at = now + timedelta(seconds=delay)
        append_event(
            db,
            run,
            "retry_scheduled",
            summary="transient failure will retry",
            data={"attempt": run.attempt_count, "delay_seconds": delay},
        )
    elif classification == "uncertain":
        transition_run(db, run, "uncertain", failure_class="uncertain", safe_error=safe_error)
    else:
        transition_run(db, run, "failed", failure_class=classification, safe_error=safe_error)
    run.lease_owner = ""
    run.lease_expires_at = None
    if run.workflow_id:
        db.query(JarvisWorkflow).filter_by(id=run.workflow_id, active_run_id=run.id).update(
            {JarvisWorkflow.active_run_id: None}, synchronize_session=False
        )
    return run


def complete_run(
    db: DbSession,
    run: JarvisRun,
    worker_id: str,
    result_summary: str = "",
) -> JarvisRun:
    if run.state != "running" or run.lease_owner != worker_id:
        raise ValueError("lease_not_owned")
    transition_run(db, run, "succeeded", result_summary=result_summary)
    run.lease_owner = ""
    run.lease_expires_at = None
    if run.workflow_id:
        db.query(JarvisWorkflow).filter_by(id=run.workflow_id, active_run_id=run.id).update(
            {JarvisWorkflow.active_run_id: None}, synchronize_session=False
        )
    return run

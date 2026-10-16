"""Durable, conservative lifecycle handling for Aide → DSH coding runs."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import (
    AideCodingRun,
    AideCodingRunEvent,
    DshConnection,
    SessionLocal,
)
from services.coding_backends.dsh import (
    DshBackend,
    DshBusinessError,
    DshConfigurationError,
    DshProtocolError,
    DshTransportError,
)

CONNECTION_ID = "default"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_STATES = frozenset(
    {"starting", "awaiting_prompt", "running", "cancel_requested", "uncertain", "interrupted"}
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value else None


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _installed() -> bool:
    return Path("/Applications/DeepSeek Harness.app").exists()


def connection_status(db: DbSession) -> dict:
    row = db.get(DshConnection, CONNECTION_ID)
    if row:
        return {
            "backend": "deepseek-harness",
            "installed": _installed(),
            "configured": True,
            "available": False,
            "reason": "connected; availability has not been checked",
            "base_url": row.base_url,
            "host_version": row.host_version or "",
            "connected_at": _iso(row.connected_at),
            "checked_at": _iso(row.checked_at),
            "credential_location": "encrypted_database",
        }
    capability = DshBackend().capability()
    if capability["configured"]:
        capability["credential_location"] = "server_environment"
    return capability


def backend_for(db: DbSession) -> DshBackend:
    row = db.get(DshConnection, CONNECTION_ID)
    if row:
        return DshBackend(base_url=row.base_url, token=row.token)
    return DshBackend()


async def pair(db: DbSession, *, base_url: str, code: str) -> dict:
    backend, _payload = await DshBackend.claim_pairing(base_url=base_url, code=code)
    health = await backend.health()
    host = health.get("host") if isinstance(health.get("host"), dict) else {}
    row = db.get(DshConnection, CONNECTION_ID)
    if row is None:
        row = DshConnection(id=CONNECTION_ID, base_url=backend.base_url, token=backend.token)
        db.add(row)
    else:
        row.base_url = backend.base_url
        row.token = backend.token
    now = _now()
    row.host_version = str(host.get("version") or "")
    row.connected_at = now
    row.checked_at = now
    db.commit()
    return {**connection_status(db), "available": True, "reason": "", "host": host}


async def check_health(db: DbSession) -> dict:
    backend = backend_for(db)
    health = await backend.health()
    row = db.get(DshConnection, CONNECTION_ID)
    if row:
        host = health.get("host") if isinstance(health.get("host"), dict) else {}
        row.host_version = str(host.get("version") or row.host_version or "")
        row.checked_at = _now()
        db.commit()
        health.update(
            {
                "base_url": row.base_url,
                "connected_at": _iso(row.connected_at),
                "checked_at": _iso(row.checked_at),
                "credential_location": "encrypted_database",
            }
        )
    return health


def disconnect(db: DbSession) -> bool:
    row = db.get(DshConnection, CONNECTION_ID)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _append_event(
    db: DbSession,
    run: AideCodingRun,
    kind: str,
    summary: str,
    data: dict | None = None,
) -> AideCodingRunEvent:
    sequence = (
        db.query(func.max(AideCodingRunEvent.sequence))
        .filter(AideCodingRunEvent.run_id == run.id)
        .scalar()
        or 0
    ) + 1
    event = AideCodingRunEvent(
        run_id=run.id,
        sequence=sequence,
        kind=kind,
        summary=summary,
        data=json.dumps(data or {}, separators=(",", ":"), sort_keys=True),
    )
    db.add(event)
    return event


def _set_state(
    db: DbSession,
    run: AideCodingRun,
    state: str,
    *,
    kind: str,
    summary: str,
    error_code: str = "",
    safe_error: str = "",
    data: dict | None = None,
) -> None:
    changed = run.state != state or run.error_code != error_code or run.safe_error != safe_error
    run.state = state
    run.error_code = error_code
    run.safe_error = safe_error
    run.updated_at = _now()
    run.finished_at = _now() if state in TERMINAL_STATES else None
    if changed:
        _append_event(db, run, kind, summary, data)


def _transition_if_state(
    db: DbSession,
    run: AideCodingRun,
    expected: str,
    state: str,
    *,
    kind: str,
    summary: str,
    error_code: str = "",
    safe_error: str = "",
    expected_updated_at: datetime | None = None,
    data: dict | None = None,
) -> bool:
    """Claim/finish an external operation without overwriting a newer stop intent.

    The conditional write is the cross-request ownership boundary. Never hold a
    database transaction open while waiting for DSH, or expose awaiting_prompt
    while its non-idempotent queue operation is in flight.
    """
    query = db.query(AideCodingRun).filter(
        AideCodingRun.id == run.id, AideCodingRun.state == expected
    )
    if expected_updated_at is not None:
        query = query.filter(AideCodingRun.updated_at == expected_updated_at)
    changed = query.update(
        {
            "state": state,
            "error_code": error_code,
            "safe_error": safe_error,
            "updated_at": _now(),
            "finished_at": _now() if state in TERMINAL_STATES else None,
        },
        synchronize_session=False,
    )
    db.refresh(run)
    if changed:
        _append_event(db, run, kind, summary, data)
    db.commit()
    return bool(changed)


def public_run(run: AideCodingRun) -> dict:
    return {
        "id": run.id,
        "aide_session_id": run.aide_session_id,
        "workspace_id": run.workspace_id,
        "workspace_path": run.workspace_path or "",
        "provider_session_id": run.provider_session_id,
        "prompt": run.prompt,
        "state": run.state,
        "error_code": run.error_code or "",
        "safe_error": run.safe_error or "",
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
        "finished_at": _iso(run.finished_at),
        "terminal": run.state in TERMINAL_STATES,
    }


def list_runs(db: DbSession, *, limit: int = 20) -> list[dict]:
    rows = (
        db.query(AideCodingRun)
        .order_by(AideCodingRun.created_at.desc())
        .limit(max(1, min(int(limit), 100)))
        .all()
    )
    return [public_run(row) for row in rows]


def local_events(db: DbSession, run_id: str) -> list[dict]:
    rows = (
        db.query(AideCodingRunEvent)
        .filter(AideCodingRunEvent.run_id == run_id)
        .order_by(AideCodingRunEvent.sequence)
        .all()
    )
    return [
        {
            "sequence": row.sequence,
            "kind": row.kind,
            "summary": row.summary,
            "data": json.loads(row.data or "{}"),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _transport_uncertain(db: DbSession, run: AideCodingRun, exc: Exception, action: str) -> None:
    _set_state(
        db,
        run,
        "uncertain",
        kind="outcome_uncertain",
        summary=f"Alles could not verify whether DSH {action}. Inspect DSH before retrying.",
        error_code=str(exc),
        safe_error="The external outcome is uncertain; inspect DSH before retrying.",
    )
    db.commit()


async def start_run(
    db: DbSession,
    *,
    run_id: str,
    aide_session_id: str | None,
    workspace_id: str,
    workspace_path: str,
    prompt: str,
) -> tuple[AideCodingRun, bool]:
    prompt_hash = _hash_prompt(prompt)
    existing = db.get(AideCodingRun, run_id)
    if existing:
        if (
            existing.prompt_hash != prompt_hash
            or existing.workspace_id != workspace_id
            or (existing.workspace_path or "") != workspace_path
            or existing.aide_session_id != aide_session_id
        ):
            raise ValueError("coding_run_identity_conflict")
        return existing, False
    run = AideCodingRun(
        id=run_id,
        aide_session_id=aide_session_id,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        provider_session_id=run_id,
        prompt=prompt,
        prompt_hash=prompt_hash,
        state="starting",
    )
    db.add(run)
    try:
        db.flush()
        _append_event(
            db, run, "intent_saved", "Alles saved the coding request before contacting DSH."
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.get(AideCodingRun, run_id) is None:
            raise
        # The other request owns the external operation; only replay its receipt.
        return await start_run(
            db,
            run_id=run_id,
            aide_session_id=aide_session_id,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            prompt=prompt,
        )
    db.refresh(run)

    backend = backend_for(db)
    db.commit()
    try:
        created = await backend.create_session(workspace_id=workspace_id, session_id=run_id)
        returned_id = created.get("sessionId")
        if returned_id != run_id:
            raise DshProtocolError("dsh_session_identity_mismatch")
    except (DshBusinessError, DshConfigurationError) as exc:
        _transition_if_state(
            db,
            run,
            "starting",
            "failed",
            kind="session_rejected",
            summary="DSH rejected the session before accepting the coding request.",
            error_code=str(exc),
            safe_error="DSH rejected the session request.",
        )
        return run, True
    except (DshTransportError, DshProtocolError) as exc:
        _transition_if_state(
            db,
            run,
            "starting",
            "uncertain",
            kind="outcome_uncertain",
            summary="Alles could not verify whether DSH created the session. Inspect DSH before retrying.",
            error_code=str(exc),
            safe_error="The external outcome is uncertain; inspect DSH before retrying.",
        )
        return run, True

    if not _transition_if_state(
        db,
        run,
        "starting",
        "starting",
        kind="session_created",
        summary="DSH created the session. The coding request has not yet been confirmed.",
    ):
        # A stop was committed while session.create was awaiting its receipt.
        return run, True
    await _send_claimed_prompt(db, run, backend)
    return run, True


async def _send_claimed_prompt(db: DbSession, run: AideCodingRun, backend) -> AideCodingRun:
    session_id, prompt = run.provider_session_id, run.prompt
    followup = (
        db.query(AideCodingRunEvent)
        .filter_by(run_id=run.id, kind="followup_requested")
        .order_by(AideCodingRunEvent.sequence.desc())
        .first()
    )
    if followup:
        prompt = json.loads(followup.data or "{}").get("prompt") or prompt
    db.commit()
    try:
        accepted = await backend.prompt_session(session_id=session_id, prompt=prompt)
        if accepted.get("accepted") is not True:
            raise DshProtocolError("dsh_prompt_receipt_invalid")
    except (DshBusinessError, DshConfigurationError) as exc:
        _transition_if_state(
            db,
            run,
            "starting",
            "awaiting_prompt",
            kind="prompt_rejected",
            summary="DSH kept the session but rejected the coding request. It can be sent again explicitly.",
            error_code=str(exc),
            safe_error="DSH rejected the coding request; the session remains available.",
        )
        return run
    except (DshTransportError, DshProtocolError) as exc:
        _transition_if_state(
            db,
            run,
            "starting",
            "uncertain",
            kind="outcome_uncertain",
            summary="Alles could not verify whether DSH accepted the coding request. Inspect DSH before retrying.",
            error_code=str(exc),
            safe_error="The external outcome is uncertain; inspect DSH before retrying.",
        )
        return run

    _transition_if_state(
        db,
        run,
        "starting",
        "running",
        kind="prompt_accepted",
        summary="DSH accepted the coding request. Execution requires this Mac and DSH to remain available.",
    )
    return run


def _history_events(history: dict) -> list[dict]:
    normalized = []
    for entry in history.get("events", []):
        event = entry.get("event") if isinstance(entry, dict) else None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        event_type = event["type"]
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        summary = {
            "user/message": "DSH recorded the request.",
            "turn/start": "DSH started the turn.",
            "tool/call": "DSH called a tool.",
            "tool/result": "DSH received a tool result.",
            "assistant/message": "DSH produced a response.",
            "turn/end": "DSH ended the turn.",
        }.get(event_type, "")
        if not summary:
            continue
        item = {"type": event_type, "sequence": event.get("seq"), "summary": summary}
        if event_type == "tool/call":
            item["call_id"] = str(data.get("callId") or "")
            item["arguments"] = str(data.get("arguments") or "")
            item["summary"] = f"DSH requested {str(data.get('name') or 'a tool')}."
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        if event_type == "assistant/message":
            item["text"] = "\n".join(
                block["text"]
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            )
        presentation = entry.get("view") if isinstance(entry.get("view"), dict) else {}
        view = presentation.get("view") if isinstance(presentation.get("view"), dict) else {}
        if event_type == "tool/result":
            if view.get("card") == "terminal" and isinstance(view.get("output"), str):
                item["text"] = view["output"]
            if view.get("card") == "diff" and isinstance(view.get("diffs"), list):
                item["diffs"] = [
                    {
                        key: diff[key]
                        for key in ("path", "oldText", "newText", "patch")
                        if key in diff and (isinstance(diff[key], str) or diff[key] is None)
                    }
                    for diff in view["diffs"]
                    if isinstance(diff, dict)
                ]
            if isinstance(view.get("title"), str):
                item["summary"] = view["title"]
        if event_type == "turn/end":
            reason = data.get("reason")
            item["reason"] = (
                str(reason.get("kind") or "") if isinstance(reason, dict) else str(reason or "")
            )
        normalized.append(item)
    return normalized


def _end_state(reason: str, cancellation_requested: bool) -> tuple[str, str, str]:
    if reason == "completed":
        return "succeeded", "turn_completed", "DSH completed the coding turn."
    if reason == "aborted" and cancellation_requested:
        return "cancelled", "turn_cancelled", "DSH confirmed the coding turn stopped."
    if reason in {"error", "blocked", "max-tokens"}:
        return "failed", "turn_failed", f"DSH ended the coding turn: {reason}."
    return (
        "interrupted",
        "turn_interrupted",
        (
            "DSH ended or lost the turn without a completed result. Inspect its session before retrying."
        ),
    )


def saved_remote_events(db: DbSession, run_id: str) -> list[dict]:
    rows = (
        db.query(AideCodingRunEvent)
        .filter_by(run_id=run_id)
        .order_by(AideCodingRunEvent.sequence.desc())
    )
    for row in rows:
        data = json.loads(row.data or "{}")
        if isinstance(data.get("remote_events"), list):
            return data["remote_events"]
    return []


def _followup_sequence_floor(db: DbSession, run_id: str) -> tuple[int, int]:
    event = (
        db.query(AideCodingRunEvent)
        .filter_by(run_id=run_id, kind="followup_requested")
        .order_by(AideCodingRunEvent.sequence.desc())
        .first()
    )
    return (
        (int(json.loads(event.data or "{}").get("after_sequence", -1)), event.sequence)
        if event
        else (-1, -1)
    )


async def refresh_run(db: DbSession, run: AideCodingRun) -> tuple[AideCodingRun, list[dict]]:
    db.refresh(run)
    expected_state, expected_updated_at = run.state, run.updated_at
    session_id = run.provider_session_id
    cached = saved_remote_events(db, run.id)
    sequence_floor, followup_event_sequence = _followup_sequence_floor(db, run.id)
    if run.state == "starting":
        db.commit()
        return run, cached
    cancellation_requested = (
        db.query(AideCodingRunEvent)
        .filter(
            AideCodingRunEvent.run_id == run.id,
            AideCodingRunEvent.kind == "cancel_requested",
            AideCodingRunEvent.sequence > followup_event_sequence,
        )
        .count()
        > 0
    )
    backend = backend_for(db)
    # Capture the read snapshot and release SQLite before either remote await.
    db.commit()

    def finish(state, kind, summary, *, error_code="", safe_error="", events=None):
        if expected_state in TERMINAL_STATES:
            # A later outage or deleted DSH session never erases a verified receipt.
            db.refresh(run)
            db.commit()
            return run, cached
        changed = _transition_if_state(
            db,
            run,
            expected_state,
            state,
            kind=kind,
            summary=summary,
            error_code=error_code,
            safe_error=safe_error,
            expected_updated_at=expected_updated_at,
            data={"remote_events": events} if events is not None else None,
        )
        return run, events if changed and events is not None else saved_remote_events(db, run.id)

    try:
        sessions = await backend.list_sessions()
        items = sessions.get("items") if isinstance(sessions.get("items"), list) else []
        remote = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("sessionId") == session_id
            ),
            None,
        )
        if remote is None:
            return finish(
                "uncertain",
                "session_not_listed",
                "DSH did not list this session. Inspect DSH before retrying the request.",
                error_code="dsh_session_not_listed",
                safe_error="DSH did not list the session; the external outcome is uncertain.",
            )
        history = await backend.session_history(session_id)
    except (DshBusinessError, DshTransportError, DshProtocolError) as exc:
        return finish(
            "uncertain",
            "refresh_unavailable",
            "DSH could not provide a verified session status. Inspect DSH before retrying.",
            error_code=str(exc),
            safe_error="DSH could not verify this session.",
        )

    events = _history_events(history)
    turn_end = next(
        (
            event
            for event in reversed(events)
            if event["type"] == "turn/end"
            and isinstance(event.get("sequence"), int)
            and event["sequence"] > sequence_floor
        ),
        None,
    )
    if expected_state in TERMINAL_STATES:
        if (
            not cached
            and turn_end
            and _end_state(str(turn_end.get("reason") or ""), cancellation_requested)[0]
            == expected_state
        ):
            _transition_if_state(
                db,
                run,
                expected_state,
                expected_state,
                expected_updated_at=expected_updated_at,
                kind="output_refreshed",
                summary="DSH returned the completed turn output.",
                data={"remote_events": events},
            )
        return run, saved_remote_events(db, run.id)
    if turn_end:
        state, kind, summary = _end_state(str(turn_end.get("reason") or ""), cancellation_requested)
    elif remote.get("running") is True:
        state = "cancel_requested" if cancellation_requested else "running"
        kind = "cancel_pending" if cancellation_requested else "status_verified"
        summary = (
            "DSH still reports the turn active. The stop request has no final receipt yet."
            if cancellation_requested
            else "DSH reports that the coding turn is running on this Mac."
        )
    elif remote.get("blank") is True and not cancellation_requested:
        state, kind, summary = (
            "awaiting_prompt",
            "blank_session_verified",
            "DSH has the session but no turn. The saved request can be sent explicitly.",
        )
    else:
        state, kind, summary = (
            "interrupted",
            "inactive_without_receipt",
            "DSH reports no active turn and no completion receipt. Inspect the session before retrying.",
        )
    return finish(state, kind, summary, events=events)


async def continue_run(
    db: DbSession, run: AideCodingRun, *, request_id: str, prompt: str
) -> AideCodingRun:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("coding_prompt_required")
    db.refresh(run)
    for event in db.query(AideCodingRunEvent).filter_by(run_id=run.id, kind="followup_requested"):
        data = json.loads(event.data or "{}")
        if data.get("request_id") == request_id:
            if data.get("prompt_hash") != _hash_prompt(prompt):
                raise ValueError("coding_run_identity_conflict")
            return run
    if run.state not in TERMINAL_STATES:
        raise ValueError("coding_run_still_active")
    expected_state, expected_updated_at = run.state, run.updated_at
    after_sequence = max(
        (
            event.get("sequence", -1)
            for event in saved_remote_events(db, run.id)
            if isinstance(event.get("sequence"), int)
        ),
        default=-1,
    )
    if after_sequence < 0:
        raise ValueError("coding_refresh_required_before_followup")
    backend = backend_for(db)
    changed = (
        db.query(AideCodingRun)
        .filter(
            AideCodingRun.id == run.id,
            AideCodingRun.state == expected_state,
            AideCodingRun.updated_at == expected_updated_at,
        )
        .update(
            {
                "state": "starting",
                "safe_error": "",
                "error_code": "",
                "finished_at": None,
                "updated_at": _now(),
            },
            synchronize_session=False,
        )
    )
    db.refresh(run)
    if not changed:
        db.commit()
        raise ValueError("coding_run_still_active")
    _append_event(
        db,
        run,
        "followup_requested",
        "Alles saved the follow-up before sending it to the same DSH session.",
        {
            "request_id": request_id,
            "prompt_hash": _hash_prompt(prompt),
            "prompt": prompt,
            "after_sequence": after_sequence,
        },
    )
    db.commit()
    return await _send_claimed_prompt(db, run, backend)


async def resume_prompt(db: DbSession, run: AideCodingRun) -> AideCodingRun:
    backend = backend_for(db)
    if not _transition_if_state(
        db,
        run,
        "awaiting_prompt",
        "starting",
        kind="prompt_sending",
        summary="Alles claimed the saved request before sending it to DSH.",
    ):
        raise ValueError("coding_run_not_awaiting_prompt")
    return await _send_claimed_prompt(db, run, backend)


async def cancel_run(db: DbSession, run: AideCodingRun) -> AideCodingRun:
    db.refresh(run)
    if run.state in TERMINAL_STATES:
        return run
    if not _transition_if_state(
        db,
        run,
        run.state,
        "cancel_requested",
        expected_updated_at=run.updated_at,
        kind="cancel_requested",
        summary="Alles saved the stop request before contacting DSH.",
    ):
        return run
    backend = backend_for(db)
    session_id = run.provider_session_id
    db.commit()
    try:
        result = await backend.cancel_session(session_id)
        if result.get("accepted") is not True:
            raise DshProtocolError("dsh_cancel_receipt_invalid")
    except DshBusinessError as exc:
        _transition_if_state(
            db,
            run,
            "cancel_requested",
            "uncertain",
            kind="cancel_rejected",
            summary="DSH rejected the stop request. Inspect the session before retrying.",
            error_code=str(exc),
            safe_error="DSH did not accept the stop request.",
        )
        return run
    except (DshTransportError, DshProtocolError) as exc:
        _transition_if_state(
            db,
            run,
            "cancel_requested",
            "uncertain",
            kind="outcome_uncertain",
            summary="Alles could not verify whether DSH accepted the stop request. Inspect DSH before retrying.",
            error_code=str(exc),
            safe_error="The external outcome is uncertain; inspect DSH before retrying.",
        )
        return run
    db.refresh(run)
    _append_event(
        db,
        run,
        "cancel_accepted",
        "DSH accepted the stop request. Refresh to verify the final turn state.",
    )
    db.commit()
    return run


def reconcile_interrupted_runs() -> dict:
    db = SessionLocal()
    counts = {"interrupted": 0, "uncertain": 0}
    try:
        rows = db.query(AideCodingRun).filter(AideCodingRun.state.in_(ACTIVE_STATES)).all()
        for run in rows:
            last_event = (
                db.query(AideCodingRunEvent)
                .filter_by(run_id=run.id)
                .order_by(AideCodingRunEvent.sequence.desc())
                .first()
            )
            unverified_legacy_prompt = run.state == "awaiting_prompt" and (
                not last_event
                or last_event.kind not in {"prompt_rejected", "blank_session_verified"}
            )
            if run.state == "running":
                _set_state(
                    db,
                    run,
                    "interrupted",
                    kind="tracking_interrupted",
                    summary=(
                        "Alles restarted while this run was last known active. DSH may still have "
                        "work; refresh before retrying."
                    ),
                )
                counts["interrupted"] += 1
            elif (
                run.state in {"starting", "cancel_requested", "uncertain"}
                or unverified_legacy_prompt
            ):
                _set_state(
                    db,
                    run,
                    "uncertain",
                    kind="tracking_uncertain",
                    summary=(
                        "Alles restarted before the external outcome was verified. Inspect DSH "
                        "before retrying."
                    ),
                    error_code="alles_restarted_before_receipt",
                    safe_error="The external outcome was not verified before Alles restarted.",
                )
                counts["uncertain"] += 1
        db.commit()
        return counts
    finally:
        db.close()

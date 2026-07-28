"""Owner-scoped Discord transport for the optional Jarvis bot.

Jarvis is a channel name only. Messages are handed to the normal Aide
background runtime and mutations remain behind Alles approval gates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import secrets
from datetime import UTC, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from core.database import (
    JarvisConnector,
    JarvisDeliveryAttempt,
    JarvisInboxEvent,
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisWorkflow,
    Session,
    SessionLocal,
)
from services import jarvis_handoff, jarvis_outbox, secretstore
from services.jarvis_store import (
    answer_choice,
    answer_questions,
    append_event,
    json_text,
    json_value,
)

log = logging.getLogger("alles.jarvis.discord")

API_BASE = "https://discord.com/api/v10"
PAIRING_TTL = timedelta(minutes=10)
PAIRING_MAX_FAILURES = 5
PAIRING_MAX_REQUESTERS = 64
PAIRING_GLOBAL_MAX_FAILURES = PAIRING_MAX_REQUESTERS * PAIRING_MAX_FAILURES
PAIRING_REJECTED_EVENT_LIMIT = 64
INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "uncertain"}
NOTICE_STATES = TERMINAL_STATES | {"waiting_input", "waiting_approval"}
_restart_event = asyncio.Event()
_runtime_loop: asyncio.AbstractEventLoop | None = None
_stream_messages: dict[str, dict] = {}
_TYPING_REFRESH_SECONDS = 7.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _config(row: JarvisConnector) -> dict:
    return json_value(row.config, dict)


def _save_config(row: JarvisConnector, value: dict) -> None:
    row.config = json_text(value, expected=dict, limit=16_000)


def _owner_generation(config: dict) -> str:
    return str(config.get("owner_generation") or "")[:64]


def _new_owner_generation() -> str:
    return secrets.token_hex(16)


def _pairing_purpose(connector_id: str) -> str:
    return f"jarvis.discord.pairing.{connector_id}"


def _new_pairing_code(row: JarvisConnector) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    config = _config(row)
    config.pop("pairing_hash", None)
    config["pairing_proof"] = secretstore.seal(code, _pairing_purpose(row.id))
    config["pairing_expires_at"] = (_utcnow() + PAIRING_TTL).isoformat()
    config["pairing_failures"] = {}
    config["pairing_failure_count"] = 0
    config["pairing_rejected_events"] = []
    if not _owner_generation(config):
        config["owner_generation"] = _new_owner_generation()
    _save_config(row, config)
    return code


def public_connection(row: JarvisConnector | None) -> dict:
    if row is None:
        return {"configured": False}
    config = _config(row)
    expires = str(config.get("pairing_expires_at") or "")
    return {
        "configured": True,
        "id": row.id,
        "bot_name": str(config.get("bot_name") or row.name or "Jarvis"),
        "bot_id": str(config.get("bot_id") or ""),
        "enabled": bool(row.enabled),
        "paired": bool(config.get("owner_user_id")),
        "owner_name": str(config.get("owner_name") or ""),
        "allowed_channel_ids": json_value(row.allowlist, list),
        "pairing_available": bool(config.get("pairing_proof") and expires),
        "pairing_expires_at": expires,
        "connection_state": str(config.get("connection_state") or "disconnected"),
        "last_connected_at": str(config.get("last_connected_at") or ""),
        "quiet_hours": config.get("quiet_hours")
        if isinstance(config.get("quiet_hours"), dict)
        else {},
        "secret_configured": bool(row.secret),
    }


def news_delivery_status(row: JarvisConnector | None) -> dict:
    """Return only the safe readiness state needed by the News settings UI."""
    if row is None:
        return {"available": False, "paired": False, "reason": "Jarvis is not connected"}
    config = _config(row)
    channel_id = _news_delivery_channel(row)
    paired = bool(config.get("owner_user_id"))
    available = bool(row.enabled and paired and channel_id)
    reason = (
        ""
        if available
        else (
            "Jarvis is paused"
            if not row.enabled
            else "pair Jarvis first"
            if not paired
            else "message Jarvis once before enabling delivery"
        )
    )
    return {"available": available, "paired": paired, "reason": reason}


def _news_delivery_channel(row: JarvisConnector) -> str:
    config = _config(row)
    direct = str(config.get("owner_channel_id") or "").strip()
    if direct:
        return direct
    owner_id = str(config.get("owner_user_id") or "")
    mapping = config.get("channel_sessions")
    if not owner_id or not isinstance(mapping, dict):
        return ""
    for key in reversed(mapping):
        user_id, separator, channel_id = str(key).partition(":")
        if separator and user_id == owner_id and channel_id:
            return channel_id
    return ""


def get_connection(db) -> JarvisConnector | None:
    return (
        db.query(JarvisConnector)
        .filter(JarvisConnector.kind == "discord")
        .order_by(JarvisConnector.created_at)
        .first()
    )


async def validate_token(token: str) -> dict:
    token = str(token or "").strip()
    if not token:
        raise ValueError("discord_token_required")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{API_BASE}/users/@me", headers={"Authorization": f"Bot {token}"}
        )
    if response.status_code == 401:
        raise ValueError("discord_token_invalid")
    response.raise_for_status()
    identity = response.json()
    if not identity.get("bot") or not identity.get("id"):
        raise ValueError("discord_bot_token_required")
    return identity


def configure(db, token: str, identity: dict) -> tuple[JarvisConnector, str]:
    row = get_connection(db)
    if row is None:
        row = JarvisConnector(name="Jarvis", kind="discord", external=True)
        db.add(row)
        db.flush()
    config = _config(row)
    config.update(
        {
            "bot_id": str(identity.get("id") or ""),
            "bot_name": str(identity.get("global_name") or identity.get("username") or "Jarvis")[
                :100
            ],
            "connection_state": "connecting",
        }
    )
    # Replacing the token is explicit owner action. Keep an existing owner pairing,
    # but create a code when this is a new or currently unpaired connection.
    row.name = "Jarvis"
    row.secret = str(token).strip()
    row.enabled = True
    _save_config(row, config)
    code = "" if config.get("owner_user_id") else _new_pairing_code(row)
    db.commit()
    db.refresh(row)
    notify_config_changed()
    return row, code


def issue_pairing_code(db, row: JarvisConnector, *, revoke_owner: bool = False) -> str:
    config = _config(row)
    if revoke_owner:
        previous_generation = _owner_generation(config)
        previous_run_ids = {
            run.id
            for run, _origin in _origin_events(
                db,
                row.id,
                owner_generation=previous_generation,
                limit=200,
                states=NOTICE_STATES | {"queued", "running"},
            )
        }
        config.pop("owner_user_id", None)
        config.pop("owner_name", None)
        config.pop("owner_channel_id", None)
        config.pop("channel_sessions", None)
        config["owner_generation"] = _new_owner_generation()
        _save_config(row, config)
        (
            db.query(JarvisDeliveryAttempt)
            .filter(
                JarvisDeliveryAttempt.connector_id == row.id,
                JarvisDeliveryAttempt.channel == "discord",
                JarvisDeliveryAttempt.state.in_(("pending", "retry", "delivering")),
            )
            .update(
                {
                    JarvisDeliveryAttempt.state: "cancelled",
                    JarvisDeliveryAttempt.safe_error_class: "owner_revoked",
                    JarvisDeliveryAttempt.next_attempt_at: None,
                    JarvisDeliveryAttempt.lease_owner: "",
                    JarvisDeliveryAttempt.lease_expires_at: None,
                },
                synchronize_session=False,
            )
        )
        for run_id in previous_run_ids:
            _stream_messages.pop(run_id, None)
            jarvis_handoff.clear_stream(run_id)
    code = _new_pairing_code(row)
    db.commit()
    return code


def update_connection(
    db,
    row: JarvisConnector,
    *,
    enabled: bool | None = None,
    allowed_channel_ids: list[str] | None = None,
    quiet_hours: dict | None = None,
) -> JarvisConnector:
    if enabled is not None:
        row.enabled = bool(enabled)
    if allowed_channel_ids is not None:
        clean: list[str] = []
        for value in allowed_channel_ids:
            value = str(value or "").strip()
            if value and value.isdigit() and value not in clean:
                clean.append(value)
        row.allowlist = json_text(clean[:100], expected=list, limit=8_000)
    if quiet_hours is not None:
        config = _config(row)
        config["quiet_hours"] = _normalize_quiet_hours(quiet_hours)
        _save_config(row, config)
    db.commit()
    db.refresh(row)
    notify_config_changed()
    return row


def _normalize_quiet_hours(value: dict) -> dict:
    if not value or value.get("enabled") is False:
        return {"enabled": False}
    start = str(value.get("start") or "23:00").strip()
    end = str(value.get("end") or "07:00").strip()
    timezone = str(value.get("timezone") or "UTC").strip()
    normalized_times: list[str] = []
    for item in (start, end):
        try:
            hour, minute = (int(part) for part in item.split(":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_quiet_hours") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("invalid_quiet_hours")
        normalized_times.append(f"{hour:02d}:{minute:02d}")
    start, end = normalized_times
    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise ValueError("invalid_quiet_timezone") from exc
    return {"enabled": True, "start": start, "end": end, "timezone": timezone}


def in_quiet_hours(config: dict, now: datetime | None = None) -> bool:
    quiet = config.get("quiet_hours")
    if not isinstance(quiet, dict) or not quiet.get("enabled"):
        return False
    try:
        zone = ZoneInfo(str(quiet.get("timezone") or "UTC"))
        current = (now or _utcnow()).astimezone(zone).strftime("%H:%M")
        start = str(quiet["start"])
        end = str(quiet["end"])
    except Exception:
        return False
    if start == end:
        return True
    return start <= current < end if start < end else current >= start or current < end


def notify_config_changed() -> None:
    loop = _runtime_loop
    if loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(_restart_event.set)
    except RuntimeError:
        pass


def _valid_pairing(row: JarvisConnector, code: str) -> bool:
    config = _config(row)
    try:
        expires = datetime.fromisoformat(str(config.get("pairing_expires_at") or ""))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
    except ValueError:
        return False
    proof = str(config.get("pairing_proof") or "")
    try:
        expected = secretstore.unseal(proof, _pairing_purpose(row.id))
    except secretstore.SecretStoreError:
        return False
    return expires > _utcnow() and secrets.compare_digest(expected, code)


def _remember_event(db, message_id: str) -> JarvisInboxEvent | None:
    dedupe = hashlib.sha256(f"discord:{message_id}".encode()).hexdigest()
    if db.query(JarvisInboxEvent).filter_by(dedupe_key=dedupe).first():
        return None
    row = JarvisInboxEvent(
        source_kind="discord",
        source_id=str(message_id)[:128],
        event_type="message_create",
        safe_summary="Discord message received",
        external=True,
        state="pending",
        dedupe_key=dedupe,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    return row


def _pairing_event_digest(message_id: str) -> str:
    return hashlib.sha256(f"discord:{message_id}".encode()).hexdigest()


def _origin_events(
    db,
    connector_id: str,
    *,
    owner_generation: str,
    limit: int | None = None,
    offset: int = 0,
    states: set[str] | None = None,
) -> list[tuple[JarvisRun, dict]]:
    query = (
        db.query(JarvisRunEvent, JarvisRun)
        .join(JarvisRun, JarvisRun.id == JarvisRunEvent.run_id)
        .filter(JarvisRunEvent.kind == "handoff_requested")
        .filter(func.json_extract(JarvisRunEvent.data, "$.origin_connector_id") == connector_id)
        .filter(
            func.coalesce(func.json_extract(JarvisRunEvent.data, "$.origin_generation"), "")
            == owner_generation
        )
        .order_by(JarvisRun.created_at.desc())
    )
    if states:
        query = query.filter(JarvisRun.state.in_(states))
    rows = query.offset(offset).limit(limit).all() if limit is not None else query.all()
    out = []
    for event, run in rows:
        data = json_value(event.data, dict)
        out.append((run, data))
    return out


def _channel_session(
    db, row: JarvisConnector, *, user_id: str, channel_id: str, content: str
) -> Session:
    config = _config(row)
    generation = _owner_generation(config)
    mapping = config.get("channel_sessions")
    mapping = dict(mapping) if isinstance(mapping, dict) else {}
    key = f"{user_id}:{channel_id}"
    session_id = str(mapping.get(key) or "")
    session = db.get(Session, session_id) if session_id else None
    if session and not session.archived and not session.incognito:
        return session

    for previous, origin in _origin_events(
        db,
        row.id,
        owner_generation=generation,
        limit=100,
    ):
        if str(origin.get("origin_channel_id") or "") != channel_id or not previous.session_id:
            continue
        candidate = db.get(Session, previous.session_id)
        if candidate and not candidate.archived and not candidate.incognito:
            session = candidate
            break

    if session is None:
        session = Session(name=content[:80] or "Discord conversation", mode="chat")
        db.add(session)
        db.flush()

    mapping.pop(key, None)
    mapping[key] = session.id
    while len(mapping) > 100:
        mapping.pop(next(iter(mapping)))
    config["channel_sessions"] = mapping
    _save_config(row, config)
    return session


def _status_text(db, row: JarvisConnector) -> str:
    items = _origin_events(
        db,
        row.id,
        owner_generation=_owner_generation(_config(row)),
        limit=5,
    )
    if not items:
        return "No recent Aide work from Discord."
    lines = ["Recent Aide work:"]
    for run, _data in items:
        workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
        workflow_name = workflow.name if workflow else "work"
        lines.append(f"• {workflow_name[:70]} — {run.state.replace('_', ' ')}")
    return "\n".join(lines)[:1900]


def _structured_discord_answer(schema: dict, value: str) -> dict:
    value = str(value or "").strip()
    if value.casefold() == "cancel":
        return {"cancelled": True, "answers": {}}
    questions = schema.get("questions") if isinstance(schema.get("questions"), list) else []
    if len(questions) == 1 and "=" not in value:
        parts = [f"{questions[0]['id']}={value}"]
    else:
        parts = [part.strip() for part in value.split(";") if part.strip()]
    parsed = {}
    for part in parts:
        question_id, separator, raw = part.partition("=")
        question_id = question_id.strip()
        if not separator or not question_id or question_id in parsed:
            raise ValueError("question_answer_invalid")
        selected = []
        free_text = ""
        for item in [token.strip() for token in raw.split(",") if token.strip()]:
            if item.casefold().startswith("text:"):
                if free_text:
                    raise ValueError("question_free_text_invalid")
                free_text = item[5:].strip()
            else:
                selected.append(item)
        parsed[question_id] = {"selected": selected, "free_text": free_text}
    return {"cancelled": False, "answers": parsed}


def _answer_command(db, row: JarvisConnector, content: str) -> str:
    parts = content.split(maxsplit=2)
    if len(parts) < 3:
        return "Use: answer <question id> <choice>"
    prompt = db.get(JarvisRunPrompt, parts[1])
    if not prompt or prompt.kind != "choice":
        return "That choice is unavailable. Approvals must be handled inside Alles."
    run = db.get(JarvisRun, prompt.run_id) if prompt.run_id else None
    if not run:
        return "That choice is no longer available."
    matching_origin = (
        db.query(JarvisRunEvent.id)
        .filter(
            JarvisRunEvent.run_id == run.id,
            JarvisRunEvent.kind == "handoff_requested",
            func.json_extract(JarvisRunEvent.data, "$.origin_connector_id") == row.id,
            func.coalesce(func.json_extract(JarvisRunEvent.data, "$.origin_generation"), "")
            == _owner_generation(_config(row)),
        )
        .first()
    )
    if not matching_origin:
        return "That choice is no longer available."
    try:
        schema = json_value(prompt.question_schema, dict)
        if schema:
            answer_questions(db, prompt, _structured_discord_answer(schema, parts[2]))
        else:
            answer_choice(db, prompt, parts[2])
        db.commit()
    except ValueError:
        db.rollback()
        return "That choice is no longer available."
    workflow = db.get(JarvisWorkflow, run.workflow_id) if run and run.workflow_id else None
    if run and workflow and workflow.deterministic_action == jarvis_handoff.HANDOFF_ACTION:
        from services.agent_runtime import resolve_user_question_from_jarvis

        answer_data = json_value(prompt.answer_data, dict)
        if not resolve_user_question_from_jarvis(prompt.id, answer_data):
            jarvis_handoff.launch(prompt.run_id)
    return "Choice saved. Aide will continue."


async def process_message(connector_id: str, payload: dict) -> list[tuple[str, str]]:
    """Process one MESSAGE_CREATE payload and return channel/text replies."""
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    if author.get("bot") or payload.get("webhook_id"):
        return []
    message_id = str(payload.get("id") or "").strip()
    channel_id = str(payload.get("channel_id") or "").strip()
    user_id = str(author.get("id") or "").strip()
    content = str(payload.get("content") or "").strip()[:4000]
    if not message_id or not channel_id or not user_id or not content:
        return []

    db = SessionLocal()
    launch_run_id = ""
    try:
        row = db.get(JarvisConnector, connector_id)
        if not row or row.kind != "discord" or not row.enabled:
            return []
        config = _config(row)
        owner_id = str(config.get("owner_user_id") or "")
        is_dm = not bool(payload.get("guild_id"))

        if not owner_id:
            if not is_dm or not content.lower().startswith("pair "):
                return []
        else:
            allowed = set(json_value(row.allowlist, list))
            if user_id != owner_id or (not is_dm and channel_id not in allowed):
                return []

        if not owner_id:
            event_digest = _pairing_event_digest(message_id)
            rejected_events = config.get("pairing_rejected_events")
            if not isinstance(rejected_events, list):
                rejected_events = []
            rejected_events = [
                value
                for value in rejected_events[-PAIRING_REJECTED_EVENT_LIMIT:]
                if isinstance(value, str) and len(value) == 64
            ]
            if event_digest in rejected_events:
                return []
            code = content.split(maxsplit=1)[1].strip()
            failures_by_user = config.get("pairing_failures")
            if not isinstance(failures_by_user, dict):
                failures_by_user = {}
            requester_failures = int(failures_by_user.get(user_id) or 0)
            total_failures = int(config.get("pairing_failure_count") or 0)
            tracking_full = (
                user_id not in failures_by_user and len(failures_by_user) >= PAIRING_MAX_REQUESTERS
            )
            may_attempt = (
                requester_failures < PAIRING_MAX_FAILURES
                and total_failures < PAIRING_GLOBAL_MAX_FAILURES
                and not tracking_full
            )
            if not may_attempt or not _valid_pairing(row, code):
                if may_attempt:
                    failures_by_user[user_id] = requester_failures + 1
                    total_failures += 1
                    config["pairing_failures"] = failures_by_user
                    config["pairing_failure_count"] = total_failures
                rejected_events.append(event_digest)
                config["pairing_rejected_events"] = rejected_events[-PAIRING_REJECTED_EVENT_LIMIT:]
                _save_config(row, config)
                db.commit()
                return [(channel_id, "That pairing code is invalid or expired.")]
            inbox = _remember_event(db, message_id)
            if inbox is None:
                return []
            config["owner_user_id"] = user_id
            config["owner_name"] = str(
                author.get("global_name") or author.get("username") or "owner"
            )[:100]
            config["owner_channel_id"] = channel_id
            config.pop("pairing_hash", None)
            config.pop("pairing_proof", None)
            config.pop("pairing_expires_at", None)
            config.pop("pairing_failures", None)
            config.pop("pairing_failure_count", None)
            config.pop("pairing_rejected_events", None)
            _save_config(row, config)
            inbox.state = "dispatched"
            db.commit()
            return [(channel_id, "Paired. I’m Jarvis here; Aide does the work inside Alles.")]

        inbox = _remember_event(db, message_id)
        if inbox is None:
            return []

        lowered = content.lower()
        if lowered in {"status", "/status"}:
            reply = _status_text(db, row)
        elif lowered.startswith("answer ") or lowered.startswith("/answer "):
            reply = _answer_command(db, row, content.lstrip("/"))
        else:
            session = _channel_session(
                db,
                row,
                user_id=user_id,
                channel_id=channel_id,
                content=content,
            )
            run = jarvis_handoff.create_handoff(
                db,
                session,
                content,
                permission_mode="approve",
                effort="medium",
                origin={
                    "kind": "discord",
                    "connector_id": row.id,
                    "generation": _owner_generation(config),
                    "channel_id": channel_id,
                    "message_id": message_id,
                },
            )
            launch_run_id = run.id
            inbox.entity_kind = "run"
            inbox.entity_id = run.id
            reply = ""
        inbox.state = "dispatched"
        inbox.dispatched_at = _utcnow()
        db.commit()
    finally:
        db.close()
    if launch_run_id:
        jarvis_handoff.launch(launch_run_id)
    return [(channel_id, reply)] if reply else []


def _discord_content(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("<aide-artifact") and ">" not in text:
        return ""
    text = re.sub(r"<aide-artifact\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</aide-artifact\s*>", "", text, flags=re.IGNORECASE).strip()
    if len(text) <= 1900:
        return text
    return f"{text[:1899].rstrip()}…"


async def _api_create_message_result(
    token: str,
    channel_id: str,
    content: str,
    *,
    nonce: str = "",
) -> tuple[str, str]:
    body = {
        "content": _discord_content(content),
        "allowed_mentions": {"parse": []},
    }
    if nonce:
        body.update({"nonce": str(nonce)[:25], "enforce_nonce": True})
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{API_BASE}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            json=body,
        )
    if response.status_code >= 300:
        classification = (
            "transient"
            if response.status_code == 429 or response.status_code >= 500
            else "permanent"
        )
        return classification, ""
    try:
        message_id = str(response.json().get("id") or "")
    except (TypeError, ValueError):
        message_id = ""
    return ("delivered", message_id) if message_id else ("transient", "")


async def _api_create_message(token: str, channel_id: str, content: str, *, nonce: str = "") -> str:
    classification, message_id = await _api_create_message_result(
        token,
        channel_id,
        content,
        nonce=nonce,
    )
    return message_id if classification == "delivered" else ""


async def _api_message(token: str, channel_id: str, content: str, *, nonce: str = "") -> bool:
    return bool(await _api_create_message(token, channel_id, content, nonce=nonce))


async def deliver_news_brief(content: str, *, idempotency_key: str = "") -> str:
    """Deliver one durable News brief to the paired owner's last known channel."""
    db = SessionLocal()
    try:
        row = get_connection(db)
        if not row or not news_delivery_status(row)["available"]:
            return "unavailable"
        config = _config(row)
        if in_quiet_hours(config):
            return "deferred"
        token = row.secret
        channel_id = _news_delivery_channel(row)
    finally:
        db.close()
    try:
        nonce = ""
        if idempotency_key:
            nonce = hashlib.sha256(f"discord-news:{idempotency_key}".encode()).hexdigest()[:25]
        return (
            "delivered" if await _api_message(token, channel_id, content, nonce=nonce) else "failed"
        )
    except Exception:
        return "failed"


async def _api_edit_message(token: str, channel_id: str, message_id: str, content: str) -> bool:
    return await _api_edit_message_result(token, channel_id, message_id, content) == "delivered"


async def _api_edit_message_result(
    token: str,
    channel_id: str,
    message_id: str,
    content: str,
) -> str:
    body = {
        "content": _discord_content(content),
        "allowed_mentions": {"parse": []},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.patch(
            f"{API_BASE}/channels/{channel_id}/messages/{message_id}",
            headers={"Authorization": f"Bot {token}"},
            json=body,
        )
    if response.status_code < 300:
        return "delivered"
    if response.status_code == 404:
        return "missing"
    if response.status_code == 429 or response.status_code >= 500:
        return "transient"
    return "permanent"


async def _api_typing(token: str, channel_id: str) -> bool:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{API_BASE}/channels/{channel_id}/typing",
            headers={"Authorization": f"Bot {token}"},
        )
    return response.status_code < 300


def _notice_key(run: JarvisRun, prompt: JarvisRunPrompt | None) -> str:
    if run.state in TERMINAL_STATES:
        return f"terminal:{run.state}"
    if prompt is not None:
        return f"prompt:{prompt.id}"
    updated = run.updated_at.isoformat() if run.updated_at else "unknown"
    return f"state:{run.state}:{updated}"


def _notice_for(run: JarvisRun, prompt: JarvisRunPrompt | None) -> str:
    if run.state == "succeeded":
        return _discord_content(run.result_summary or "Done.")
    if run.state == "failed":
        return f"Aide couldn’t finish: {run.safe_error or 'open Alles for details.'}"[:1900]
    if run.state == "cancelled":
        return "Aide work was cancelled."
    if run.state == "uncertain":
        return "Aide stopped with an uncertain result. Review it inside Alles before retrying."
    if run.state == "waiting_approval":
        return "Aide needs approval inside Alles before it can change anything."
    if prompt and prompt.kind == "choice":
        schema = json_value(prompt.question_schema, dict)
        if schema:
            lines = [f"Aide needs input: {schema.get('title') or prompt.question}"]
            for index, question in enumerate(schema.get("questions", []), 1):
                mode = "choose one or more" if question.get("selection") == "multiple" else "choose one"
                lines.append(f"{index}. {question.get('prompt', '')} ({mode})")
                for choice in question.get("choices", []):
                    detail = f" - {choice['description']}" if choice.get("description") else ""
                    lines.append(f"   {choice.get('id')}: {choice.get('label')}{detail}")
                if question.get("allow_free_text"):
                    lines.append("   or use text:your answer")
            question_ids = "; ".join(
                f"{question.get('id')}=<choice>" for question in schema.get("questions", [])
            )
            lines.append(f"reply: answer {prompt.id} {question_ids}")
            lines.append(f"cancel: answer {prompt.id} cancel")
            return "\n".join(lines)[:1900]
        options = json_value(prompt.options, list)
        suffix = f" Options: {', '.join(str(item) for item in options)}" if options else ""
        return f"Aide needs a choice: {prompt.question}{suffix}\nanswer {prompt.id} <choice>"[:1900]
    return "Aide needs input. Open Alles to continue."


def _stream_nonce(run_id: str) -> str:
    return hashlib.sha256(f"discord-stream:{run_id}".encode()).hexdigest()[:25]


def _persist_stream_message(
    connector_id: str,
    owner_generation: str,
    run_id: str,
    channel_id: str,
    message_id: str,
) -> None:
    db = SessionLocal()
    try:
        connector = db.get(JarvisConnector, connector_id)
        run = db.get(JarvisRun, run_id)
        config = _config(connector) if connector else {}
        if (
            not connector
            or not connector.enabled
            or not run
            or not message_id
            or _owner_generation(config) != owner_generation
        ):
            return
        append_event(
            db,
            run,
            "discord_stream_message",
            source="discord",
            summary="Discord stream message created",
            data={
                "owner_generation": owner_generation,
                "channel_id": channel_id,
                "message_id": message_id,
            },
        )
        db.commit()
    finally:
        db.close()


def _persisted_stream_messages(
    db,
    run_ids: set[str],
    *,
    owner_generation: str,
) -> dict[str, dict]:
    if not run_ids:
        return {}
    messages: dict[str, dict] = {}
    rows = (
        db.query(JarvisRunEvent)
        .filter(
            JarvisRunEvent.run_id.in_(run_ids),
            JarvisRunEvent.kind == "discord_stream_message",
        )
        .order_by(JarvisRunEvent.created_at.desc(), JarvisRunEvent.sequence.desc())
        .all()
    )
    for event in rows:
        if event.run_id in messages:
            continue
        data = json_value(event.data, dict)
        if str(data.get("owner_generation") or "") == owner_generation and data.get("message_id"):
            messages[event.run_id] = data
    return messages


def _stream_state(run_id: str, owner_generation: str, channel_id: str) -> dict:
    stream = _stream_messages.get(run_id)
    if stream is not None:
        return stream
    db = SessionLocal()
    try:
        persisted = _persisted_stream_messages(
            db,
            {run_id},
            owner_generation=owner_generation,
        ).get(run_id)
    finally:
        db.close()
    stream = {}
    if persisted and str(persisted.get("channel_id") or "") == channel_id:
        stream["message_id"] = str(persisted.get("message_id") or "")
    _stream_messages[run_id] = stream
    return stream


async def _refresh_typing(token: str, run_id: str, channel_id: str) -> None:
    stream = _stream_messages.setdefault(run_id, {})
    now = monotonic()
    if now - float(stream.get("last_typing") or 0) < _TYPING_REFRESH_SECONDS:
        return
    try:
        sent = await _api_typing(token, channel_id)
    except Exception:
        sent = False
    if sent:
        stream["last_typing"] = now


def _delivery_channel_allowed(row: JarvisConnector, config: dict, channel_id: str) -> bool:
    owner_channel_id = str(config.get("owner_channel_id") or "")
    return channel_id == owner_channel_id or channel_id in set(json_value(row.allowlist, list))


def _current_stream_token(connector_id: str, owner_generation: str, channel_id: str) -> str:
    db = SessionLocal()
    try:
        row = db.get(JarvisConnector, connector_id)
        config = _config(row) if row else {}
        if (
            not row
            or not row.enabled
            or not config.get("owner_user_id")
            or _owner_generation(config) != owner_generation
            or not _delivery_channel_allowed(row, config, channel_id)
            or in_quiet_hours(config)
        ):
            return ""
        return str(row.secret or "")
    finally:
        db.close()


async def _deliver_stream(
    token: str,
    connector_id: str,
    owner_generation: str,
    run_id: str,
    channel_id: str,
) -> None:
    token = _current_stream_token(connector_id, owner_generation, channel_id)
    if not token:
        return
    stream = _stream_state(run_id, owner_generation, channel_id)
    content = _discord_content(jarvis_handoff.stream_text(run_id))
    message_id = str(stream.get("message_id") or "")
    previous = str(stream.get("content") or "")
    try:
        if content and not message_id:
            message_id = await _api_create_message(
                token,
                channel_id,
                content,
                nonce=_stream_nonce(run_id),
            )
            if message_id:
                stream.update({"message_id": message_id, "content": content})
                _persist_stream_message(
                    connector_id,
                    owner_generation,
                    run_id,
                    channel_id,
                    message_id,
                )
        elif content and content != previous:
            edit_result = await _api_edit_message_result(token, channel_id, message_id, content)
            if edit_result == "delivered":
                stream["content"] = content
            elif edit_result == "missing":
                stream.pop("message_id", None)
                replacement_id = await _api_create_message(
                    token,
                    channel_id,
                    content,
                    nonce=_stream_nonce(run_id),
                )
                if replacement_id:
                    stream.update({"message_id": replacement_id, "content": content})
                    _persist_stream_message(
                        connector_id,
                        owner_generation,
                        run_id,
                        channel_id,
                        replacement_id,
                    )
    except Exception:
        pass
    await _refresh_typing(token, run_id, channel_id)


async def _discord_outbox_provider(payload: dict, *, idempotency_key: str, connector) -> dict:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    channel_id = str(context.get("channel_id") or "")
    content = str(payload.get("summary") or "")
    owner_generation = str(context.get("owner_generation") or "")
    streamed_message_id = str(context.get("streamed_message_id") or "")
    if not connector or not channel_id or not content:
        return {"classification": "permanent"}

    def current_delivery_authority() -> tuple[str, str]:
        db = SessionLocal()
        try:
            current = db.get(JarvisConnector, connector.id)
            config = _config(current) if current else {}
            if (
                not current
                or not current.enabled
                or current.kind != "discord"
                or not current.secret
                or not config.get("owner_user_id")
                or _owner_generation(config) != owner_generation
                or not _delivery_channel_allowed(current, config, channel_id)
            ):
                return "permanent", ""
            if in_quiet_hours(config):
                return "transient", ""
            return "ready", str(current.secret)
        finally:
            db.close()

    try:
        authority, token = current_delivery_authority()
        if authority != "ready":
            return {"classification": authority, "provider_message_id": ""}
        if streamed_message_id:
            edit_result = await _api_edit_message_result(
                token, channel_id, streamed_message_id, content
            )
            if edit_result == "missing":
                authority, token = current_delivery_authority()
                if authority != "ready":
                    return {"classification": authority, "provider_message_id": ""}
                classification, provider_message_id = await _api_create_message_result(
                    token,
                    channel_id,
                    content,
                    nonce=idempotency_key[:25],
                )
            else:
                provider_message_id = streamed_message_id if edit_result == "delivered" else ""
                classification = edit_result
        else:
            nonce = (
                _stream_nonce(str(payload.get("run_id") or idempotency_key))
                if payload.get("state") in TERMINAL_STATES
                else idempotency_key[:25]
            )
            classification, provider_message_id = await _api_create_message_result(
                token,
                channel_id,
                content,
                nonce=nonce,
            )
    except Exception:
        provider_message_id = ""
        classification = "transient"
    return {
        "classification": classification,
        "provider_message_id": provider_message_id,
    }


def _legacy_notice_sent(events: list[JarvisRunEvent], run: JarvisRun, notice_key: str) -> bool:
    for event in events:
        data = json_value(event.data, dict)
        if data.get("notice_key") == notice_key:
            return True
        if (
            not data.get("notice_key")
            and data.get("state") == run.state
            and (not run.updated_at or not event.created_at or event.created_at >= run.updated_at)
        ):
            return True
    return False


def _record_discord_receipts(connector_id: str) -> list[str]:
    db = SessionLocal()
    completed_runs: list[str] = []
    try:
        connector = db.get(JarvisConnector, connector_id)
        current_generation = _owner_generation(_config(connector)) if connector else ""
        page_size = 200
        offset = 0
        receipt_budget = 200
        sent_receipt = aliased(JarvisRunEvent)
        sent_notice_key = func.coalesce(func.json_extract(sent_receipt.data, "$.notice_key"), "")
        queued_notice_key = func.coalesce(
            func.json_extract(JarvisRunEvent.data, "$.notice_key"), ""
        )
        matching_receipt = (
            db.query(sent_receipt.id)
            .filter(
                sent_receipt.run_id == JarvisRun.id,
                sent_receipt.kind == "discord_notice_sent",
                or_(
                    sent_notice_key == queued_notice_key,
                    and_(
                        sent_notice_key == "",
                        func.json_extract(sent_receipt.data, "$.state") == JarvisRun.state,
                        or_(
                            JarvisRun.updated_at.is_(None),
                            sent_receipt.created_at.is_(None),
                            sent_receipt.created_at >= JarvisRun.updated_at,
                        ),
                    ),
                ),
            )
            .exists()
        )
        while receipt_budget > 0:
            rows = (
                db.query(JarvisDeliveryAttempt, JarvisRunEvent, JarvisRun)
                .join(JarvisRunEvent, JarvisRunEvent.id == JarvisDeliveryAttempt.event_id)
                .join(JarvisRun, JarvisRun.id == JarvisDeliveryAttempt.run_id)
                .filter(
                    JarvisDeliveryAttempt.connector_id == connector_id,
                    JarvisDeliveryAttempt.channel == "discord",
                    JarvisDeliveryAttempt.state == "delivered",
                    JarvisRunEvent.kind == "discord_notice_queued",
                    func.coalesce(func.json_extract(JarvisRunEvent.data, "$.owner_generation"), "")
                    == current_generation,
                    func.coalesce(func.json_extract(JarvisRunEvent.data, "$.notice_key"), "") != "",
                    ~matching_receipt,
                )
                .order_by(JarvisDeliveryAttempt.updated_at.desc())
                .offset(offset)
                .limit(page_size)
                .all()
            )
            if not rows:
                break
            offset += len(rows)
            run_ids = {run.id for _delivery, _event, run in rows}
            sent_by_run: dict[str, list[JarvisRunEvent]] = {run_id: [] for run_id in run_ids}
            for event in db.query(JarvisRunEvent).filter(
                JarvisRunEvent.run_id.in_(run_ids),
                JarvisRunEvent.kind == "discord_notice_sent",
            ):
                sent_by_run.setdefault(event.run_id, []).append(event)
            for delivery, queued, run in rows:
                context = json_value(queued.data, dict)
                if str(context.get("owner_generation") or "") != current_generation:
                    continue
                notice_key = str(context.get("notice_key") or "")
                if not notice_key or _legacy_notice_sent(
                    sent_by_run.get(run.id, []), run, notice_key
                ):
                    continue
                sent = append_event(
                    db,
                    run,
                    "discord_notice_sent",
                    source="discord",
                    summary="Discord notice sent",
                    data={
                        "state": run.state,
                        "notice_key": notice_key,
                        "owner_generation": current_generation,
                        "channel_id": context.get("channel_id", ""),
                        "message_id": delivery.provider_message_id,
                        "streamed": bool(
                            context.get("streamed_message_id")
                            and context.get("streamed_message_id") == delivery.provider_message_id
                        ),
                    },
                )
                sent_by_run.setdefault(run.id, []).append(sent)
                completed_runs.append(run.id)
                receipt_budget -= 1
                if receipt_budget <= 0:
                    break
            if len(rows) < page_size:
                break
        db.commit()
        return completed_runs
    finally:
        db.close()


async def deliver_notices(connector_id: str) -> None:
    db = SessionLocal()
    active: list[tuple[str, str]] = []
    try:
        row = db.get(JarvisConnector, connector_id)
        config = _config(row) if row else {}
        if not row or not row.enabled or not config.get("owner_user_id"):
            return
        owner_generation = _owner_generation(config)
        quiet = in_quiet_hours(config)
        query_states = (
            (NOTICE_STATES - TERMINAL_STATES) | {"queued", "running"}
            if quiet
            else NOTICE_STATES | {"queued", "running"}
        )
        page_size = 200
        offset = 0
        new_notice_budget = 200
        stop_scanning = False
        while not stop_scanning:
            candidates = _origin_events(
                db,
                connector_id,
                owner_generation=owner_generation,
                limit=page_size,
                offset=offset,
                states=query_states,
            )
            if not candidates:
                break
            offset += len(candidates)
            run_ids = {run.id for run, _origin in candidates}
            prompts: dict[str, JarvisRunPrompt] = {}
            for prompt in (
                db.query(JarvisRunPrompt)
                .filter(
                    JarvisRunPrompt.run_id.in_(run_ids),
                    JarvisRunPrompt.state == "pending",
                )
                .order_by(JarvisRunPrompt.created_at.desc())
            ):
                prompts.setdefault(prompt.run_id, prompt)
            queued: dict[tuple[str, str], JarvisRunEvent] = {}
            sent_by_run: dict[str, list[JarvisRunEvent]] = {run_id: [] for run_id in run_ids}
            for event in db.query(JarvisRunEvent).filter(
                JarvisRunEvent.run_id.in_(run_ids),
                JarvisRunEvent.kind.in_(("discord_notice_queued", "discord_notice_sent")),
            ):
                data = json_value(event.data, dict)
                if event.kind == "discord_notice_queued" and data.get("notice_key"):
                    queued[(event.run_id, str(data["notice_key"]))] = event
                elif event.kind == "discord_notice_sent":
                    sent_by_run.setdefault(event.run_id, []).append(event)
            persisted_streams = _persisted_stream_messages(
                db,
                run_ids,
                owner_generation=owner_generation,
            )

            for run, origin in candidates:
                channel_id = str(origin.get("origin_channel_id") or "")
                if not channel_id:
                    continue
                if run.state in {"queued", "running"}:
                    active.append((run.id, channel_id))
                    continue
                prompt = prompts.get(run.id)
                notice_key = _notice_key(run, prompt)
                if _legacy_notice_sent(sent_by_run.get(run.id, []), run, notice_key):
                    continue
                event = queued.get((run.id, notice_key))
                if event is None:
                    if new_notice_budget <= 0:
                        stop_scanning = True
                        break
                    stream_message_id = str(
                        _stream_messages.get(run.id, {}).get("message_id") or ""
                    )
                    if not stream_message_id:
                        persisted = persisted_streams.get(run.id, {})
                        if str(persisted.get("channel_id") or "") == channel_id:
                            stream_message_id = str(persisted.get("message_id") or "")
                    event = append_event(
                        db,
                        run,
                        "discord_notice_queued",
                        source="discord",
                        summary=_notice_for(run, prompt),
                        data={
                            "notice_key": notice_key,
                            "owner_generation": owner_generation,
                            "channel_id": channel_id,
                            "streamed_message_id": stream_message_id,
                        },
                    )
                    queued[(run.id, notice_key)] = event
                    new_notice_budget -= 1
                jarvis_outbox.enqueue_delivery(
                    db,
                    run,
                    channel="discord",
                    privacy_level="summary",
                    event_id=event.id,
                    connector_id=connector_id,
                    idempotency_supported=True,
                )
            if len(candidates) < page_size:
                break
        token = row.secret
        db.commit()
    finally:
        db.close()

    for run_id, channel_id in active:
        await _deliver_stream(token, connector_id, owner_generation, run_id, channel_id)
    await jarvis_outbox.process_outbox(worker_id=f"discord-{connector_id}", limit=100)
    for run_id in _record_discord_receipts(connector_id):
        _stream_messages.pop(run_id, None)
        jarvis_handoff.clear_stream(run_id)


async def _set_runtime_state(connector_id: str, state: str, **values) -> None:
    db = SessionLocal()
    try:
        row = db.get(JarvisConnector, connector_id)
        if not row:
            return
        config = _config(row)
        config["connection_state"] = state
        config.update(values)
        _save_config(row, config)
        db.commit()
    finally:
        db.close()


async def _disable_revoked_token(connector_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(JarvisConnector, connector_id)
        if not row:
            return
        row.enabled = False
        config = _config(row)
        config["connection_state"] = "token revoked"
        _save_config(row, config)
        db.commit()
    finally:
        db.close()


async def _save_gateway_sequence(connector_id: str, sequence) -> None:
    db = SessionLocal()
    try:
        row = db.get(JarvisConnector, connector_id)
        if not row:
            return
        config = _config(row)
        config["gateway_sequence"] = sequence
        _save_config(row, config)
        db.commit()
    finally:
        db.close()


async def _send_gateway_heartbeat(
    websocket,
    interval: float,
    sequence,
    state: dict,
    *,
    require_previous_ack: bool,
) -> bool:
    async with state["lock"]:
        if require_previous_ack:
            remaining = float(state.get("deadline") or 0) - monotonic()
            if remaining > 0:
                return False
            if not state["acknowledged"]:
                raise RuntimeError("discord_gateway_heartbeat_unacknowledged")
        state["acknowledged"] = False
        state["deadline"] = monotonic() + interval
        await websocket.send(json.dumps({"op": 1, "d": sequence()}))
        return True


async def _heartbeat(websocket, interval: float, sequence, state: dict) -> None:
    await asyncio.sleep(interval * random.random())
    while True:
        remaining = float(state.get("deadline") or 0) - monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)
            continue
        sent = await _send_gateway_heartbeat(
            websocket,
            interval,
            sequence,
            state,
            require_previous_ack=True,
        )
        if sent:
            await asyncio.sleep(interval)


async def _notice_loop(connector_id: str) -> None:
    while True:
        try:
            await deliver_notices(connector_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("discord notice delivery failed; retrying")
        await asyncio.sleep(1.5)


async def _handle_invalid_gateway_session(
    connector_id: str,
    *,
    resumable: bool,
    handled_sequence,
):
    checkpoint = handled_sequence if resumable else None
    state = {"gateway_sequence": checkpoint}
    if not resumable:
        state.update({"gateway_session_id": "", "resume_gateway_url": ""})
    await _set_runtime_state(connector_id, "reconnecting", **state)
    await asyncio.sleep(random.uniform(1.0, 5.0))
    return checkpoint


async def _gateway_session(connector_id: str) -> None:
    import websockets

    db = SessionLocal()
    try:
        row = db.get(JarvisConnector, connector_id)
        if not row or not row.enabled or not row.secret:
            return
        token = row.secret
        config = _config(row)
        resume_url = str(config.get("resume_gateway_url") or "")
        resume_session = str(config.get("gateway_session_id") or "")
        resume_sequence = config.get("gateway_sequence")
    finally:
        db.close()

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{API_BASE}/gateway/bot", headers={"Authorization": f"Bot {token}"}
        )
    if response.status_code == 401:
        await _disable_revoked_token(connector_id)
        return
    response.raise_for_status()
    gateway_url = resume_url or str(response.json().get("url") or "")
    if not gateway_url:
        raise RuntimeError("discord_gateway_missing")
    url = f"{gateway_url.rstrip('/')}?v=10&encoding=json"
    # Discord heartbeats acknowledge the newest packet seen on this live socket, while reconnects
    # must resume only after the corresponding dispatch finished. Keep those two sequence meanings
    # separate: ``sequence`` is live protocol state and only ``handled_sequence`` is persisted.
    sequence = resume_sequence
    handled_sequence = resume_sequence
    heartbeat_task = None
    notice_task = None
    receive_task = None
    restart_task = None
    heartbeat_state = {
        "acknowledged": True,
        "deadline": 0.0,
        "lock": asyncio.Lock(),
    }
    await _set_runtime_state(connector_id, "connecting")
    # Match the trust configuration already used by the working Discord HTTPS calls. On macOS,
    # asyncio's bare default context can miss the CA bundle that httpx loads successfully.
    gateway_ssl = httpx.create_ssl_context(trust_env=True)
    async with websockets.connect(
        url,
        ssl=gateway_ssl,
        max_size=2_000_000,
        ping_interval=None,
    ) as websocket:
        hello = json.loads(await websocket.recv())
        if hello.get("op") != 10:
            raise RuntimeError("discord_gateway_hello_missing")
        interval = float(hello["d"]["heartbeat_interval"]) / 1000
        heartbeat_task = asyncio.create_task(
            _heartbeat(websocket, interval, lambda: sequence, heartbeat_state),
            name="jarvis-discord-heartbeat",
        )
        if resume_session:
            await websocket.send(
                json.dumps(
                    {
                        "op": 6,
                        "d": {"token": token, "session_id": resume_session, "seq": sequence},
                    }
                )
            )
        else:
            await websocket.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": token,
                            "intents": INTENTS,
                            "properties": {
                                "os": "linux",
                                "browser": "alles",
                                "device": "alles",
                            },
                        },
                    }
                )
            )

        notice_task = asyncio.create_task(_notice_loop(connector_id), name="jarvis-discord-notices")
        try:
            while True:
                receive_task = asyncio.create_task(websocket.recv())
                restart_task = asyncio.create_task(_restart_event.wait())
                done, _pending = await asyncio.wait(
                    {receive_task, restart_task, heartbeat_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if restart_task in done:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
                    _restart_event.clear()
                    return
                if heartbeat_task in done:
                    receive_task.cancel()
                    restart_task.cancel()
                    await asyncio.gather(receive_task, restart_task, return_exceptions=True)
                    heartbeat_task.result()
                restart_task.cancel()
                await asyncio.gather(restart_task, return_exceptions=True)
                packet = json.loads(receive_task.result())
                receive_task = None
                restart_task = None
                if packet.get("s") is not None:
                    sequence = packet["s"]
                op = packet.get("op")
                if op == 1:
                    await _send_gateway_heartbeat(
                        websocket,
                        interval,
                        lambda: sequence,
                        heartbeat_state,
                        require_previous_ack=False,
                    )
                    continue
                if op == 11:
                    heartbeat_state["acknowledged"] = True
                    continue
                if op == 7:
                    return
                if op == 9:
                    resumable = packet.get("d") is True
                    handled_sequence = await _handle_invalid_gateway_session(
                        connector_id,
                        resumable=resumable,
                        handled_sequence=handled_sequence,
                    )
                    sequence = handled_sequence
                    return
                if op != 0:
                    continue
                event_type = packet.get("t")
                data = packet.get("d") if isinstance(packet.get("d"), dict) else {}
                if event_type == "READY":
                    await _set_runtime_state(
                        connector_id,
                        "connected",
                        last_connected_at=_utcnow().isoformat(),
                        gateway_session_id=str(data.get("session_id") or ""),
                        resume_gateway_url=str(data.get("resume_gateway_url") or ""),
                        gateway_sequence=sequence,
                    )
                    handled_sequence = sequence
                elif event_type == "RESUMED":
                    await _set_runtime_state(
                        connector_id,
                        "connected",
                        last_connected_at=_utcnow().isoformat(),
                        gateway_sequence=sequence,
                    )
                    handled_sequence = sequence
                elif event_type == "MESSAGE_CREATE":
                    replies = await process_message(connector_id, data)
                    message_id = str(data.get("id") or "")
                    if replies and not message_id:
                        raise RuntimeError("discord_message_identity_missing")
                    for index, (channel_id, text) in enumerate(replies):
                        nonce = hashlib.sha256(
                            f"discord-reply:{connector_id}:{message_id}:{index}:{channel_id}".encode()
                        ).hexdigest()[:25]
                        await _api_message(token, channel_id, text, nonce=nonce)
                    await deliver_notices(connector_id)
                    handled_sequence = sequence
                else:
                    handled_sequence = sequence
        finally:
            # This commit completes before the exception reaches ``run_forever`` and publishes the
            # reconnecting state, so a failed MESSAGE_CREATE can only resume from the older safe
            # checkpoint and will be replayed.
            await _save_gateway_sequence(connector_id, handled_sequence)
            tasks = [
                task for task in (receive_task, restart_task, heartbeat_task, notice_task) if task
            ]
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


async def run_forever() -> None:
    global _runtime_loop
    _runtime_loop = asyncio.get_running_loop()
    backoff = 1.0
    while True:
        db = SessionLocal()
        try:
            row = get_connection(db)
            connector_id = row.id if row and row.enabled and row.secret else ""
        finally:
            db.close()
        if not connector_id:
            try:
                await asyncio.wait_for(_restart_event.wait(), timeout=5)
                _restart_event.clear()
            except TimeoutError:
                pass
            continue
        try:
            await _gateway_session(connector_id)
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Jarvis Discord connection stopped: %s", type(exc).__name__)
            await _set_runtime_state(connector_id, "reconnecting")
            try:
                await asyncio.wait_for(_restart_event.wait(), timeout=backoff)
                _restart_event.clear()
            except TimeoutError:
                pass
            backoff = min(backoff * 2, 60.0)


jarvis_outbox.register_provider("discord", _discord_outbox_provider)
